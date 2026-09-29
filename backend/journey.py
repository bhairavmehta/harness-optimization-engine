"""Trace journey: one production trace followed through every harness revision.

The same customer (scenario seed) and the same random draws (sampling seed) are replayed
under each harness the engine has produced for that agent, so every difference in the
transcript, tool calls and verdicts is caused by the harness change and nothing else.
"""
from . import hood, state as st
from .engine import env, harness as H, judges, vcs

MAX_OTHER = 6   # candidates from other bundles are shown only if they change this trace


def _tools(msgs):
    return [{"name": m["name"], "args": m.get("args") or {}, "result": m["text"]} for m in msgs if m["role"] == "tool"]


def _signals(t):
    return [label for _, label, _, f in hood.SIGNALS if f(t)]


def _run(h, t, cfg):
    ep = env.run_episode(h, t["seed"], t["samp"])
    return ep, judges.evaluate_all(ep, cfg)


def _outcome(ep, j):
    return {"resolved": ep["truth"]["resolved"], "judge_pass": j["resolution"]["pass"], "judge_score": j["resolution"]["score"],
            "judge_rationale": j["resolution"]["rationale"], "policy": j["policy"]["pass"], "policy_detail": j["policy"]["detail"],
            "tool_sequence_ok": not j["tool_sequence"]["anomaly"], "tool_sequence_detail": j["tool_sequence"]["detail"],
            "repeat_contact": j["outcome"]["repeat_contact"], "csat": j["outcome"]["csat"],
            "tokens": ep["tokens"], "latency": ep["latency"]}


def _harness(h, origin):
    return {"id": h["id"], "name": h["name"], "version": h["version"], "manifest": hood.manifest_hash(h)[:12],
            "edits": [H.edit_label(e) for e in H.edits_between(origin, h)], "has_adapter": bool(h.get("adapter"))}


def _verdict(o0, o, div):
    if div < 0:
        return "No change"
    if not o0["resolved"] and o["resolved"]:
        return "Fixed"
    if o0["resolved"] and not o["resolved"]:
        return "Regressed"
    return "Changed, same outcome"


def _approval_for(hid, bid=None, fid=None):
    for ap in st.S["approvals"].values():
        if ap["harness_id"] == hid or (bid and ap.get("bundle_id") == bid and fid in ap.get("fix_ids", [])):
            ro = ap.get("rollout")
            return {"id": ap["id"], "status": ap["status"], "waiting_on": st.approval_view(ap)["waiting_on"],
                    "stage": ro["stages"][ro["stage"]]["name"] if ro and ro["stage"] >= 0 else None}
    return None


def _git_for(bid, fid):
    branch = f"hoe/{bid.lower()}-{fid.lower()}"
    pr = st.S.get("prs", {}).get(f"{bid}/{fid}")
    return {"branch": branch, "branch_url": vcs.branch_url(branch), "compare_url": vcs.compare_url(branch),
            "pr": pr and {"number": pr["pr_number"], "url": pr["pr_url"], "commits": pr["commits"]}}


def journey(tid):
    t = st.S["traces"][tid]
    aid = t["agent"]
    cfg = st.judge_cfg(aid)
    origin = st.get_h(t["harness"])
    ep0, j0 = st.S["eps"][tid]
    o0 = _outcome(ep0, j0)
    tools0 = _tools(ep0["messages"])
    stages = [{"kind": "production", "title": f"Production trace on {origin['version']}", "when": f"{t['date']} {t['time']}",
               "harness": _harness(origin, origin), "outcome": o0, "tools": tools0, "messages": ep0["messages"],
               "divergence": -1, "changed_decisions": [], "verdict": "Original", "signals": _signals(t)}]
    seen = {origin["id"]}

    def add(kind, title, h, **extra):
        if h["id"] in seen:
            return None
        seen.add(h["id"])
        ep, j = _run(h, t, cfg)
        div = env.divergence(ep0["messages"], ep["messages"])
        changed = [{"decision": env.DECISION_LABEL.get(a["d"], a["d"]),
                    "before": env.ACTION_LABEL.get(a["a"], a["a"]), "after": env.ACTION_LABEL.get(b["a"], b["a"])}
                   for a, b in zip(ep0["decisions"], ep["decisions"]) if a["d"] == b["d"] and a["a"] != b["a"]]
        o = _outcome(ep, j)
        stage = {"kind": kind, "title": title, "harness": _harness(h, origin), "outcome": o, "tools": _tools(ep["messages"]),
                 "messages": ep["messages"], "divergence": div, "changed_decisions": changed, "verdict": _verdict(o0, o, div), **extra}
        stages.append(stage)
        return stage

    prod = st.prod(aid)
    add("release", f"Released harness {prod['version']} (current production)", prod,
        note="Shipped after this trace was recorded" if prod["released_day"] > t["day"] else None)

    theme = st.S["theme_index"].get(f"{aid}-{t['theme']}") if t["theme"] else None
    bid = theme and st.S["bundle_by_theme"].get(theme["id"])
    bundles = [bid] if bid else []
    bundles += [b for b in st.S["bundles"] if st.S["bundles"][b]["agent"] == aid and b != bid]
    for b in bundles:
        bundle = st.S["bundles"][b]
        own = b == bid
        for f in bundle["fixes"]:
            if f["harness_id"] not in st.S["harnesses"]:
                continue
            h = st.get_h(f["harness_id"])
            v = f.get("validation") or {}
            lift = v.get("lift")
            extra = dict(fix={"bundle": b, "id": f["id"], "title": f["title"], "status": f["status"], "layer": f["layer"],
                              "risk": f["risk"], "lift": lift and {k: lift[k] for k in ("diff", "lo", "hi")}},
                         approval=_approval_for(h["id"], b, f["id"]), git=_git_for(b, f["id"]))
            if own:
                add("fix", f"{b} · {f['id']}: {f['title']}", h, **extra)
            elif sum(1 for s in stages if s["kind"] == "other") < MAX_OTHER:
                s = add("other", f"{b} · {f['id']}: {f['title']}", h, **extra)
                if s and s["divergence"] < 0:   # other bundles only matter when they touch this trace
                    stages.remove(s)
    for e in st.S["experiments"].values():
        if e["agent"] != aid:
            continue
        for hid in e["candidates"]:
            if hid in st.S["harnesses"]:
                add("experiment", f"{e['id']} candidate: {st.get_h(hid)['name']}", st.get_h(hid),
                    experiment={"id": e["id"], "name": e["name"], "recommended": e.get("recommended") == hid},
                    approval=_approval_for(hid))

    first_fix = next((s for s in stages[1:] if s["verdict"] == "Fixed"), None)
    audit_keys = {tid, *(s["harness"]["id"] for s in stages)} | ({bid} if bid else set()) | \
                 {s["approval"]["id"] for s in stages if s.get("approval")}
    audit = [r for r in st.S["audit"] if any(k and (k in r["obj"] or k in r["detail"]) for k in audit_keys)]
    return {
        "trace": {k: t[k] for k in ("id", "agent", "date", "time", "version", "label", "snippet", "flagged", "judged_pass",
                                    "judged_score", "gold", "repeat", "csat", "type")} | {"agent_name": st.agent(aid)["name"]},
        "theme": theme and {"id": theme["id"], "name": theme["name"], "sev": theme["sev"], "traces": theme["traces"],
                            "root_cause": theme["root_cause"]["text"], "confidence": theme["root_cause"]["confidence"],
                            "bundle": bid},
        "stages": stages,
        "summary": {"candidates": len(stages) - 1, "fixed_by": [s["title"] for s in stages[1:] if s["verdict"] == "Fixed"],
                    "regressed_by": [s["title"] for s in stages[1:] if s["verdict"] == "Regressed"],
                    "first_fix": first_fix and first_fix["title"]},
        "git": _git_panel(aid, bid, stages),
        "audit": audit[::-1][:40],
    }


def _git_panel(aid, bid, stages):
    agent = st.agent(aid)
    out = {"repo": vcs.REPO, "repo_url": vcs.repo_url(), "live": vcs.live(), "path": agent.get("repo_path"),
           "path_url": agent.get("repo_path") and vcs.file_url(agent["repo_path"]).replace("/blob/", "/tree/"),
           "prs": [s["git"] | {"title": s["title"], "fix": s["fix"]["id"]} for s in stages if s.get("git")],
           "commits": [], "error": None}
    if not agent.get("repo_path"):
        out["note"] = f"{agent['name']} has no connected repository ({agent['integration']}); changes go out as {'a vendor change request' if agent['type'] == 'Third-party' else 'a registry publish'}."
    return out


def git_commits(git):
    """Network half of the Git panel. Called outside st.LOCK so a slow GitHub never stalls the app."""
    if not git.get("path"):
        return git
    try:   # commits that touched this agent's harness files, from GitHub (cached, ETag-revalidated)
        rows = vcs._get(f"/repos/{vcs.REPO}/commits?path={git['path']}&per_page=10") or []
        git["commits"] = [{"sha": c["sha"][:7], "url": c["html_url"], "message": c["commit"]["message"].split("\n")[0],
                           "date": vcs._ts(c["commit"]["author"]["date"])} for c in rows]
        head = vcs._get(f"/repos/{vcs.REPO}/commits?sha={vcs.BASE}&per_page=1") or []
        git["main_head"] = head and {"sha": head[0]["sha"][:7], "url": head[0]["html_url"],
                                     "message": head[0]["commit"]["message"].split("\n")[0]}
    except vcs.GitHubError as e:
        git["error"] = str(e)
    return git


def search(aid, q="", limit=40):
    q = (q or "").strip().lower()
    pool = [t for t in st.S["traces"].values() if t["agent"] == aid]
    if q:
        themes = {k: v["name"].lower() for k, v in st.S["theme_index"].items()}
        pool = [t for t in pool if q in t["id"] or q in t["snippet"].lower() or q in t["label"].lower()
                or q in t["version"].lower() or (t["theme"] and q in themes.get(f"{aid}-{t['theme']}", ""))]
    pool.sort(key=lambda t: (-t["day"], t["time"]))
    rows = [_row(t) for t in pool[:limit]]
    return {"total": len(pool), "items": rows, "suggested": [] if q else _suggested(aid)}


def _row(t):
    th = st.S["theme_index"].get(f"{t['agent']}-{t['theme']}") if t["theme"] else None
    return {"id": t["id"], "date": t["date"], "time": t["time"], "version": t["version"], "label": t["label"],
            "snippet": t["snippet"], "flagged": t["flagged"], "resolved": t["gold"], "theme": th and th["name"]}


def _suggested(aid, k=3):
    """Traces whose conversation a proposed fix actually changes: the most interesting journeys."""
    out = []
    for bid, b in st.S["bundles"].items():
        if b["agent"] != aid or not b["fixes"]:
            continue
        f = b["fixes"][0]
        for ex in st.replay_examples(b["base_id"], f["harness_id"], b["theme_id"], k=k):
            if ex["fixed"]:
                out.append(_row(st.S["traces"][ex["trace_id"]]) | {"why": f"{bid} · {f['id']} fixes it"})
    return out[:8]
