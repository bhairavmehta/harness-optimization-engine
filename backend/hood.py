"""Under the hood: read-only views that expose how each part of the engine decides.

Detection, root cause, statistics, judges, release and the harness manifest hash.
Every view is computed from live state, so the numbers match the other screens.
"""
import hashlib
import json
from collections import Counter

from . import state as st
from .engine import analysis as A, evaluate as E, harness as H, judges

SIGNALS = [
    ("judge", "Resolution judge failed", "not judged_pass", lambda t: not t["judged_pass"]),
    ("policy", "Policy violation", "violation", lambda t: t["violation"]),
    ("repeat", "Repeat contact within 72h", "repeat", lambda t: t["repeat"]),
    ("toolseq", "Tool-sequence anomaly", "anomaly", lambda t: t["anomaly"]),
    ("csat", "Low CSAT (1–2)", "csat <= 2", lambda t: t["csat"] <= 2),
    ("human", "Human reviewer flag", "human_flag", lambda t: bool(t.get("human_flag"))),
]
ROLLOUT_N = [400, 250, 400, 600, 600]  # mirrors state.advance
ROLLBACK = {"resolution_drop": 0.01, "violation_rise": 0.004}


def _traces(aid):
    return [t for t in st.S["traces"].values() if t["agent"] == aid]


def _versions(aid):
    return sorted([h for h in st.S["harnesses"].values() if h["agent"] == aid and "released_day" in h],
                  key=lambda h: h["released_day"])


# ------------------------------------------------------------------ detection
def detection(aid):
    ts = _traces(aid)
    flagged = [t for t in ts if t["flagged"]]
    hits = {t["id"]: [k for k, _, _, f in SIGNALS if f(t)] for t in flagged}
    signals = []
    for k, label, expr, f in SIGNALS:
        n = sum(1 for t in ts if f(t))
        sole = sum(1 for t in flagged if hits[t["id"]] == [k])
        signals.append({"key": k, "label": label, "expr": expr, "hits": n, "sole": sole})
    overlap = Counter(len(v) for v in hits.values())
    by_theme = Counter(t["theme"] for t in flagged)
    order = [{"key": th["key"], "name": th["name"], "layer": th["layer"], "assigned": by_theme.get(th["key"], 0)}
             for th in A.THEMES]
    return {"traces": len(ts), "flagged": len(flagged), "rate": len(flagged) / max(1, len(ts)),
            "signals": signals, "overlap": [{"signals": k, "traces": overlap[k]} for k in sorted(overlap)],
            "themes": order}


# ------------------------------------------------------------------ root cause
def root_cause(aid):
    ts = _traces(aid)
    vers = _versions(aid)
    total = Counter(t["harness"] for t in ts)
    out = []
    for th in st.themes(aid):
        if th["key"] == "other":
            continue
        items = [t for t in ts if t["flagged"] and t["theme"] == th["key"]]
        cnt = Counter(t["harness"] for t in items)
        rows = [{"id": h["id"], "version": h["version"], "released_day": h["released_day"], "traces": total[h["id"]],
                 "hits": cnt[h["id"]], "rate": cnt[h["id"]] / total[h["id"]]} for h in vers if total[h["id"]]]
        best, change = 0.0, None
        for a, b in zip(rows, rows[1:]):
            if b["rate"] - a["rate"] > best:
                best, change = b["rate"] - a["rate"], (a, b)
        added = []
        if change:
            ha, hb = st.get_h(change[0]["id"]), st.get_h(change[1]["id"])
            added = [H.edit_label(e) for e in H.edits_between(ha, hb)]
        rc = th["root_cause"]
        out.append({"id": th["id"], "name": th["name"], "sev": th["sev"], "rows": rows, "jump": best,
                    "change": {"from": change[0]["version"], "to": change[1]["version"], "edits": added} if change else None,
                    "confidence": rc["confidence"], "text": rc["text"]})
    return {"themes": out}


# ------------------------------------------------------------------ statistics
def statistics(aid, n=400, B=500):
    base = st.prod(aid)
    cands = [h for h in st.S["harnesses"].values()
             if h["agent"] == aid and h["id"] != base["id"] and not h.get("adapter") and h.get("parent") == base["id"]]
    out = {"n": n, "B": B, "base": base["version"], "cand": None}
    if cands:
        cand = cands[0]
        cfg = st.judge_cfg(aid)
        seeds = range(40000, 40000 + n)
        br, cr = E.run(base, seeds, cfg), E.run(cand, seeds, cfg)
        out.update(cand=cand["name"], edits=[H.edit_label(e) for e in H.edits_between(base, cand)],
                   metrics={k: _bootstrap_view(br, cr, k, B) for k in ("judged_pass", "gold")})
    exps = [e for e in st.S["experiments"].values() if e["agent"] == aid]
    if exps:
        e = exps[-1]
        out["holm"] = {"id": e["id"], "name": e["name"], "rows": [
            {"name": r["name"], "diff": r["lift"]["diff"], "lo": r["lift"]["lo"], "hi": r["lift"]["hi"],
             "p": r["lift"]["p"], "p_holm": r["lift"].get("p_holm"), "significant": r.get("significant")}
            for r in e["results"][1:]]}
    return out


def _bootstrap_view(br, cr, key, B):
    x, y = [r[key] for r in br], [r[key] for r in cr]
    res = E.paired_bootstrap(x, y, B=B, return_boots=True)
    boots = res.pop("boots")
    lo_b, hi_b = min(boots), max(boots)
    bins = 24
    w = (hi_b - lo_b) / bins or 1e-9
    hist = [0] * bins
    for v in boots:
        hist[min(bins - 1, int((v - lo_b) / w))] += 1
    return {"result": res, "hist": {"lo": lo_b, "width": w, "counts": hist},
            "pairs": {"both_pass": sum(a and b for a, b in zip(x, y)), "both_fail": sum(not a and not b for a, b in zip(x, y)),
                      "gained": sum(not a and b for a, b in zip(x, y)), "lost": sum(a and not b for a, b in zip(x, y))}}


# ------------------------------------------------------------------ judges
def judges_view(aid):
    res = st.evaluator(aid, "resolution")
    ids = st.S["calibration"][aid]
    jp = [judges.resolution(st.S["eps"][i][0], res["criteria"], res["params"])["pass"] for i in ids]
    hp = [judges.human_label(st.S["eps"][i][0]) for i in ids]
    n = len(ids)
    cm = {"tp": sum(a and b for a, b in zip(jp, hp)), "fp": sum(a and not b for a, b in zip(jp, hp)),
          "fn": sum(not a and b for a, b in zip(jp, hp)), "tn": sum(not a and not b for a, b in zip(jp, hp))}
    po = (cm["tp"] + cm["tn"]) / max(1, n)
    pa, pb = sum(jp) / max(1, n), sum(hp) / max(1, n)
    pe = pa * pb + (1 - pa) * (1 - pb)
    # verbosity bias, counterfactually: re-score the same sessions with the bonus switched off
    no_bonus = {**res["params"], "verbosity_bias": 0.0}
    bad = [(i, j) for i, j, h in zip(ids, jp, hp) if not h]
    on = [judges.resolution(st.S["eps"][i][0], res["criteria"], res["params"]) for i, _ in bad]
    off = [judges.resolution(st.S["eps"][i][0], res["criteria"], no_bonus) for i, _ in bad]
    det = [k for k, (i, _) in enumerate(bad) if st.S["eps"][i][0]["obs"]["detailed"]]
    bias = {"unresolved": len(bad), "detailed": len(det),
            "score_on": sum(on[k]["score"] for k in det) / max(1, len(det)),
            "score_off": sum(off[k]["score"] for k in det) / max(1, len(det)),
            "false_pass": sum(r["pass"] for r in on), "false_pass_no_bonus": sum(r["pass"] for r in off),
            "bonus_only": sum(1 for a, b in zip(on, off) if a["pass"] and not b["pass"]),
            "criteria": len(res["criteria"])}
    evs = [{k: v for k, v in e.items() if k not in ("history",)} for e in st.evaluators(aid)["items"]]
    return {"params": res["params"], "criteria": [{"id": c, "text": H.CRITERIA[c]} for c in res["criteria"]],
            "confusion": cm, "n": n, "po": po, "pe": pe, "kappa": E.kappa(jp, hp), "threshold": st.S["kappa_threshold"],
            "bias": bias, "evaluators": evs}


# ------------------------------------------------------------------ release
def release(aid):
    sid = st.S["suite_by_agent"].get(aid)
    su = st.S["suites"].get(sid) if sid else None
    aps = [st.approval_view(a) for a in st.S["approvals"].values() if a["agent"] == aid]
    return {"policy": st.POLICY, "stages": [{"name": s, "n": n} for s, n in zip(st.STAGES, ROLLOUT_N)],
            "rollback": ROLLBACK, "third_party": st.agent(aid)["type"] == "Third-party",
            "gate": su and {"suite": sid, "tests": len(su["tests"]), **su["gate"], "last_run": su["last_run"]},
            "approvals": [{"id": a["id"], "title": a["title"], "change_type": a["change_type"], "risk": a["risk"],
                           "status": a["status"], "waiting_on": a["waiting_on"],
                           "stage": (a["rollout"] or {}).get("stage", -1) if a["rollout"] else None} for a in aps]}


# ------------------------------------------------------------------ manifest hash
def manifest(h):
    """Canonical, content-only description of a harness. Names and version labels are excluded,
    so two harnesses with identical behaviour share a hash."""
    ad = h.get("adapter")
    return {
        "schema": "hoe.harness/1",
        "agent": h["agent"],
        "system_prompt": [{"id": l, "text": H.LINES[l]["text"], "frozen": H.is_frozen(l)} for l in h["lines"]],
        "gates": [{"id": g, "text": H.GATES[g]["text"]} for g in sorted(h["gates"])],
        "tools": {t: H.TOOLS[t][v] for t, v in sorted(h["tools"].items())},
        "evaluator_criteria": sorted(h["criteria"]),
        "adapter_sha256": _sha(ad) if ad else None,
    }


def _sha(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def manifest_hash(h):
    return _sha(manifest(h))


def frozen_hash(h):
    return _sha([H.LINES[l]["text"] for l in h["lines"] if H.is_frozen(l)])


def manifests(aid):
    pid = st.S["production"].get(aid)
    rows = []
    for h in st.S["harnesses"].values():
        if h["agent"] != aid:
            continue
        rows.append({"id": h["id"], "name": h["name"], "version": h["version"], "parent": h.get("parent"),
                     "production": h["id"] == pid, "released": "released_day" in h, "has_adapter": bool(h.get("adapter")),
                     "hash": manifest_hash(h), "frozen": frozen_hash(h)})
    dupes = Counter(r["hash"] for r in rows)
    for r in rows:
        r["shared"] = dupes[r["hash"]] > 1
    prod_h = st.get_h(pid) if pid else None
    return {"items": rows, "production": prod_h and {"id": pid, "manifest": manifest(prod_h), "hash": manifest_hash(prod_h)},
            "frozen_ok": len({r["frozen"] for r in rows}) <= 1}


def verify_hash(aid, value):
    value = (value or "").strip().lower()
    if len(value) < 8:
        raise ValueError("Paste at least the first 8 characters of a manifest hash.")
    hits = [r for r in manifests(aid)["items"] if r["hash"].startswith(value)]
    return {"match": bool(hits), "items": hits}
