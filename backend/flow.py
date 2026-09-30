"""Core flow: one trace taken through the eight steps of the optimization workflow.

Failed traces → failure themes → RCA categories → RCA solution bundles → experiments →
human approval → regression → staged rollout. Each step reports what happened to this
trace there (replayed with the same customer and random draws, so differences come from
the harness alone), the in-app pages that show it, and the GitHub revisions behind it:
the code that implements the step, pinned to the commit that last changed it on main,
and the fix branch, pull request and commits that carry this trace's harness change.
"""
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

from . import hood, journey, state as st
from .engine import env, harness as H, vcs

STEPS = [
    (1, "failed", "Failed traces"), (2, "themes", "Failure themes"), (3, "rca", "RCA categories"),
    (4, "bundles", "RCA solution bundles"), (5, "experiments", "Experiments"), (6, "approval", "Human approval"),
    (7, "regression", "Regression"), (8, "rollout", "Staged rollout"),
]
CODE = {  # the code that implements each step (mirrors the Intro page's flow diagram)
    "failed": ["backend/engine/judges.py", "backend/engine/env.py", "backend/hood.py"],
    "themes": ["backend/engine/analysis.py"],
    "rca": ["backend/engine/analysis.py", "backend/engine/harness.py"],
    "bundles": ["backend/engine/optimizer.py", "backend/engine/rl.py", "backend/state.py"],
    "experiments": ["backend/engine/evaluate.py", "backend/state.py"],
    "approval": ["backend/state.py"],
    "regression": ["backend/state.py"],
    "rollout": ["backend/state.py", "backend/engine/vcs.py"],
}
# Verizon lookup table: failure signature → business meaning (step 2 input)
LOOKUP = {
    "premature": ("close_ticket within one turn of quote_credit, no confirmation", "Repeat contact on disputed bills", "FCR, repeat-contact rate"),
    "silent": ("close_ticket after a single idle period", "Abandoned session, customer calls back", "Containment, CSAT"),
    "policy": ("apply_credit above $150 without supervisor", "Revenue leakage and audit exposure", "Credit-policy compliance"),
    "eta": ("restoration time stated before outage_status", "Missed ETA promises, escalations", "Containment, CSAT"),
    "other": ("no shared signature", "Needs human review", "Judge accuracy"),
}
# RCA category per theme (step 3), in the taxonomy the Intro page uses
RCA_CATEGORY = {
    "premature": "Intent was missed", "silent": "Conversation ended early", "policy": "Policy not enforced in tools",
    "eta": "Answer not grounded in a tool", "other": "Unclassified",
}


def _step(n, key, name, status, headline, **extra):
    return {"n": n, "key": key, "name": name, "status": status, "headline": headline,
            "code": CODE[key], "links": [], "revisions": [], **extra}


def _check(h, t):
    """Run this trace as a regression test against harness h: its scenario's assertion, same seeds."""
    a = st.TYPE_ASSERTION.get(t["type"], "tool_order")
    ep = env.run_episode(h, t["seed"], t["samp"])
    return bool(st.ASSERTIONS[a][2](ep["obs"]))


def _pr_revisions(git, fix_label, folder):
    """Links for a fix branch: live ones when the PR exists, the planned branch otherwise."""
    pr = git.get("pr")
    files = [f"{folder}/system_prompt.md", f"{folder}/harness.yaml"] if folder else []
    if not pr:
        return [{"kind": "branch", "label": f"{fix_label}: branch {git['branch']}", "planned": True,
                 "note": "Not on GitHub yet. Open the pull request from the fix page (needs GITHUB_TOKEN)."}]
    out = [{"kind": "pr", "label": f"{fix_label}: PR #{pr['number']}", "url": pr["url"]},
           {"kind": "branch", "label": git["branch"], "url": git["branch_url"]}]
    out += [{"kind": "file", "label": f, "url": vcs.file_url(f, git["branch"])} for f in files]
    out += [{"kind": "commit", "label": f"{c['short']} {c['message']}", "url": c["url"]} for c in pr["commits"]]
    return out


def flow(tid):
    j = journey.journey(tid)
    t = st.S["traces"][tid]
    aid, tr, theme = t["agent"], j["trace"], j["theme"]
    a = st.agent(aid)
    folder = a.get("repo_path")
    stages = j["stages"]
    prod0 = stages[0]
    fixes = [s for s in stages if s["kind"] == "fix"]
    others = [s for s in stages if s["kind"] == "other"]
    exps = [s for s in stages if s["kind"] == "experiment"]
    by_h = {s["harness"]["id"]: s for s in stages}
    steps = []

    # 1 · failed traces ---------------------------------------------------------------
    sig = prod0["signals"]
    s1 = _step(1, "failed", "Failed traces", "done" if t["flagged"] else "stop",
               f"Flagged by {len(sig)} signal{'s' if len(sig) != 1 else ''}" if t["flagged"] else "Not flagged: no signal fired",
               signals=[{"label": label, "hit": bool(f(t))} for _, label, _, f in hood.SIGNALS],
               outcome=prod0["outcome"], tools=prod0["tools"], harness=prod0["harness"], messages=prod0["messages"],
               human_label=st.S["labels"].get(tid))
    s1["links"] = [["Evidence explorer", f"#/traces/{tid}"], ["Evaluator health", "#/evaluators"], ["Judges", "#/judges"],
                   ["Detection", "#/detection"]]
    steps.append(s1)

    # 2 · failure themes --------------------------------------------------------------
    if theme:
        th = st.S["theme_index"][theme["id"]]
        key = th["key"]
        sub = env.SCENARIO_LABEL.get(t["type"], t["type"])
        sig_, meaning, kpi = LOOKUP.get(key, LOOKUP["other"])
        s2 = _step(2, "themes", "Failure themes", "done", f"Clustered into “{th['name']}”",
                   theme={"id": th["id"], "name": th["name"], "sev": th["sev"], "traces": th["traces"], "share": th["share"],
                          "trend": th["trend"], "first_seen": th.get("first_seen"), "layer": th["layer"], "desc": th["desc"],
                          "subcluster": sub, "sub_share": next((c["share"] for c in th["subclusters"] if c["label"] == sub), None)},
                   lookup={"signature": sig_, "meaning": meaning, "kpi": kpi})
        s2["links"] = [[th["name"], f"#/themes/{th['id']}"], ["All themes", "#/themes"]]
    else:
        key = None
        s2 = _step(2, "themes", "Failure themes", "skipped", "Not clustered: only flagged traces join a theme")
        s2["links"] = [["All themes", "#/themes"]]
    steps.append(s2)

    # 3 · RCA categories --------------------------------------------------------------
    if theme:
        rc = th["root_cause"]
        ch = rc.get("change")
        release = None
        if ch:
            v0, v1 = st.get_h(ch["from"]), st.get_h(ch["to"])
            release = {"from": v0["version"], "to": v1["version"], "day": v1.get("released_day"),
                       "edits": [H.edit_label(e) for e in H.edits_between(v0, v1)],
                       "this_trace": t["harness"] == v1["id"]}
        frozen = [{"id": l, "text": H.LINES[l]["text"]} for l in st.prod(aid)["lines"] if H.is_frozen(l)]
        s3 = _step(3, "rca", "RCA categories", "done", RCA_CATEGORY.get(key, "Unclassified"),
                   category=RCA_CATEGORY.get(key, "Unclassified"), root_cause=rc["text"], confidence=rc["confidence"],
                   layers=rc["layers"], release=release, frozen=frozen)
        s3["links"] = [["Root cause", "#/rootcause"], ["Manifest hash", "#/manifest"]]
    else:
        s3 = _step(3, "rca", "RCA categories", "skipped", "No theme, so no root cause")
        s3["links"] = [["Root cause", "#/rootcause"]]
    steps.append(s3)

    # 4 · RCA solution bundles (harness optimization, RL optimization) ------------------
    def fix_row(s):
        f = s["fix"]
        return {"bundle": f["bundle"], "id": f["id"], "title": f["title"], "layer": f["layer"], "risk": f["risk"],
                "status": f["status"], "lift": f["lift"], "verdict": s["verdict"], "resolved": s["outcome"]["resolved"],
                "judge_pass": s["outcome"]["judge_pass"], "changed": s["changed_decisions"], "edits": s["harness"]["edits"],
                "version": s["harness"]["version"], "divergence": s["divergence"]}
    rl_cands = [s for s in exps if s["harness"]["has_adapter"]]
    opt = [h for h in st.S["harnesses"].values() if h["agent"] == aid and "-OPT-" in h["id"]]
    bid = theme and theme.get("bundle")
    fixed_by = [s for s in fixes + others if s["verdict"] == "Fixed"]
    if fixes or others:
        head = (f"{fixed_by[0]['fix']['bundle']} · {fixed_by[0]['fix']['id']} fixes this trace in replay" if fixed_by
                else f"{bid or 'Bundles'}: no fix changes this trace's outcome")
        s4 = _step(4, "bundles", "RCA solution bundles", "done", head)
    else:
        s4 = _step(4, "bundles", "RCA solution bundles", "skipped" if not theme else "pending",
                   "No fix bundle touches this trace" if not theme else "No bundle proposed for this theme yet")
    s4.update(bundle=bid, fixes=[fix_row(s) for s in fixes], other_fixes=[fix_row(s) for s in others],
              rl=[{"name": s["harness"]["name"], "id": s["harness"]["id"], "verdict": s["verdict"],
                   "resolved": s["outcome"]["resolved"], "judge_pass": s["outcome"]["judge_pass"]} for s in rl_cands],
              optimizer=[{"id": h["id"], "name": h["name"]} for h in opt][-3:])
    s4["links"] = ([[f"Bundle {bid}", f"#/fixes/{bid}/F-1"]] if bid else []) + [["Fix bundles", "#/fixes"], ["Optimizer & RL", "#/optimizer"]]
    if folder:
        for s in fixes + [o for o in others if o["verdict"] == "Fixed"]:
            s4["revisions"] += _pr_revisions(s["git"], f"{s['fix']['bundle']} · {s['fix']['id']}", folder)
    elif fixes:
        s4["revisions"].append({"kind": "note", "label": f"{a['name']} has no connected repository ({a['integration']}): fixes ship as "
                                + ("a vendor change request" if a["type"] == "Third-party" else "a registry publish") + ", not a pull request."})
    steps.append(s4)

    # 5 · experiments -----------------------------------------------------------------
    rows = []
    for e in st.S["experiments"].values():
        if e["agent"] != aid:
            continue
        res = {r["id"]: r for r in e["results"]}
        for hid in e["candidates"][1:]:
            s = by_h.get(hid)
            r = res.get(hid, {})
            rows.append({"exp": e["id"], "exp_name": e["name"], "id": hid, "name": st.get_h(hid)["name"],
                         "recommended": e.get("recommended") == hid, "significant": r.get("significant"),
                         "lift": r.get("lift") and {k: r["lift"].get(k) for k in ("diff", "lo", "hi", "p_holm")},
                         "gold_lift": r.get("gold_lift") and r["gold_lift"]["diff"],
                         "resolution": r.get("metrics", {}).get("resolution"), "has_adapter": r.get("has_adapter"),
                         "audit": r.get("audit"),
                         "verdict": s["verdict"] if s else "No change",
                         "resolved": s["outcome"]["resolved"] if s else prod0["outcome"]["resolved"],
                         "judge_pass": s["outcome"]["judge_pass"] if s else prod0["outcome"]["judge_pass"]})
    rec = next((r for r in rows if r["recommended"]), None)
    s5 = _step(5, "experiments", "Experiments", "done" if rows else "pending",
               (f"{rec['exp']} recommends {rec['name'].split(':')[0]}: {'fixes' if rec['verdict'] == 'Fixed' else rec['verdict'].lower()} for this trace"
                if rec else f"{len(rows)} candidates compared" if rows else "No experiment for this agent yet"),
               candidates=rows)
    s5["links"] = sorted({(f"Experiment {r['exp']}", f"#/experiments/{r['exp']}") for r in rows}) + [["Experiments", "#/experiments"],
                                                                                                         ["Statistics", "#/statistics"]]
    steps.append(s5)

    # 6 · human approval --------------------------------------------------------------
    hids = {s["harness"]["id"] for s in stages[1:]}
    aps = [st.approval_view(ap) for ap in st.S["approvals"].values()
           if ap["agent"] == aid and (ap["harness_id"] in hids or (bid and ap.get("bundle_id") == bid))]
    rank = {"Live": 0, "Rolling out": 1, "Approved": 2, "Waiting": 3, "Changes requested": 4, "Rolled back": 5, "Rejected": 6}
    aps.sort(key=lambda ap: (ap.get("bundle_id") != bid, rank.get(ap["status"], 9)))
    ap_rows = []
    for ap in aps:
        s = by_h.get(ap["harness_id"])
        ap_rows.append({"id": ap["id"], "title": ap["title"], "status": ap["status"], "change_type": ap["change_type"],
                        "risk": ap["risk"], "waiting_on": ap["waiting_on"], "approvers": ap["approvers"],
                        "harness": ap["harness_id"], "version": st.get_h(ap["harness_id"])["version"],
                        "checks": ap["checks"], "rollout": ap["rollout"], "rollout_plan": ap["rollout_plan"],
                        "verdict": s["verdict"] if s else "No change",
                        "resolved": s["outcome"]["resolved"] if s else prod0["outcome"]["resolved"]})
    main = ap_rows[0] if ap_rows else None
    pats = [{"id": p["id"], "name": p["name"], "lift": p["lift"], "proven_on": st.agent(p["proven_on"])["name"]}
            for p in st.S["patterns"] if key and p["theme_key"] == key]
    if main:
        s6 = _step(6, "approval", "Human approval",
                   "done" if main["status"] in ("Approved", "Rolling out", "Live") else "blocked" if main["status"] in ("Rejected", "Changes requested") else "active",
                   f"{main['id']} {main['status'].lower()}" + (f", waiting on {main['waiting_on']}" if main["waiting_on"] else ""),
                   approvals=ap_rows, patterns=pats)
    else:
        s6 = _step(6, "approval", "Human approval", "pending", "No change for this trace has been sent to approvers",
                   approvals=[], patterns=pats)
    s6["links"] = [[f"{ap['id']}", f"#/approvals/{ap['id']}"] for ap in ap_rows[:3]] + [["Approvals", "#/approvals"],
                                                                                      ["Pattern library", "#/patterns"], ["Audit log", f"#/audit?q={tid}"]]
    steps.append(s6)

    # 7 · regression ------------------------------------------------------------------
    sid = st.S["suite_by_agent"].get(aid)
    su = sid and st.S["suites"][sid]
    assertion = st.TYPE_ASSERTION.get(t["type"], "tool_order")
    checks = [{"label": f"Production {prod0['harness']['version']}", "harness": prod0["harness"]["id"], "pass": _check(st.get_h(t["harness"]), t)}]
    seen = {checks[0]["harness"]}
    for s in fixes + [by_h[ap["harness"]] for ap in ap_rows if ap["harness"] in by_h]:
        if s["harness"]["id"] in seen:
            continue
        seen.add(s["harness"]["id"])
        label = f"{s['fix']['bundle']} · {s['fix']['id']}" if s.get("fix") else s["harness"]["name"].split(":")[0]
        checks.append({"label": label, "harness": s["harness"]["id"], "pass": _check(st.get_h(s["harness"]["id"]), t)})
    in_suite = [x["id"] for x in (su["tests"] if su else []) if x["source"] == tid or (x["seed"] == t["seed"] and x["samp"] == t["samp"])]
    from_theme = sum(1 for x in (su["tests"] if su else []) if theme and x["source"] == theme["id"])
    gates = []
    for ap in ap_rows:
        c = ap["checks"] or {}
        if c.get("regression"):
            gates.append({"approval": ap["id"], "title": ap["title"], "result": c["regression"], "ok": c.get("regression_ok")})
    for s in fixes:
        v = (st.S["bundles"][s["fix"]["bundle"]]["fixes"])
        f = next(x for x in v if x["id"] == s["fix"]["id"])
        r = (f.get("validation") or {}).get("regression")
        if r:
            gates.append({"fix": f"{s['fix']['bundle']} · {s['fix']['id']}", "title": s["fix"]["title"],
                          "result": f"{r['passed']}/{r['total']} pass", "ok": r["gate"]})
    main_gate = next((g for g in gates if main and g.get("approval") == main["id"]), None)
    fails = [g for g in gates if not g["ok"]]
    s7 = _step(7, "regression", "Regression",
               "pending" if not gates else "done" if (main_gate or gates[0])["ok"] else "blocked",
               ("Gate passed" if (main_gate or gates[0])["ok"] else "Gate failed: back to experiments") + f" · {(main_gate or gates[0])['result']}"
               if gates else "No regression run yet",
               suite={"id": sid, "tests": len(su["tests"]) if su else 0, "min_pass": su and su["gate"]["min_pass"],
                      "policy_all": su and su["gate"]["policy_all"], "from_theme": from_theme, "last_run": su and su.get("last_run")},
               assertion={"id": assertion, "expected": st.ASSERTIONS[assertion][0], "check": st.ASSERTIONS[assertion][1]},
               trace_checks=checks, in_suite=in_suite, gates=gates, iterate=bool(fails))
    s7["links"] = [["Regression suites", "#/regression"], ["Release gate", "#/release"]]
    for s in fixes:
        pr = s["git"].get("pr")
        if pr:
            s7["revisions"].append({"kind": "pr", "label": f"CI checks on PR #{pr['number']}", "url": f"{pr['url']}/checks"})
    steps.append(s7)

    # 8 · staged rollout --------------------------------------------------------------
    cur = next((s for s in stages if s["kind"] == "release"), None)
    ro_ap = next((ap for ap in ap_rows if ap["rollout"]), None) or main
    if ro_ap and ro_ap["status"] == "Live":
        s8s, s8h = "done", f"Live: {ro_ap['id']} promoted to production"
    elif ro_ap and ro_ap["status"] == "Rolling out":
        stage = ro_ap["rollout"]["stages"][ro_ap["rollout"]["stage"]]["name"]
        s8s, s8h = "active", f"{ro_ap['id']} rolling out, passed {stage}"
    elif ro_ap and ro_ap["status"] == "Rolled back":
        s8s, s8h = "blocked", f"{ro_ap['id']} rolled back automatically"
    elif ro_ap and ro_ap["status"] == "Approved":
        s8s, s8h = "active", f"{ro_ap['id']} approved, rollout not started"
    else:
        s8s, s8h = "pending", "Waiting for approval before any traffic moves"
    s8 = _step(8, "rollout", "Staged rollout", s8s, s8h, approval=ro_ap and {k: ro_ap[k] for k in ("id", "title", "status", "rollout", "rollout_plan", "version")},
               stages=st.STAGES, production={"version": st.prod(aid)["version"], "name": st.prod(aid)["name"],
                                             "resolved": (cur or prod0)["outcome"]["resolved"],
                                             "verdict": cur["verdict"] if cur else "Original"},
               delivery=("Pull request to " + a["repo"]) if folder else
               ("Vendor change request" if a["type"] == "Third-party" else "Prompt registry publish"))
    s8["links"] = ([[f"Rollout {ro_ap['id']}", f"#/approvals/{ro_ap['id']}"]] if ro_ap else []) + [["Release", "#/release"],
                                                                                                    ["Agents & connections", "#/agents"], ["Version control", "#/vcs"]]
    if folder:
        s8["revisions"].append({"kind": "tree", "label": f"{folder}/ on {vcs.BASE}", "url": vcs.file_url(folder).replace("/blob/", "/tree/"),
                                "history": True})
    steps.append(s8)

    return {"trace": tr, "theme": theme, "steps": steps, "summary": j["summary"], "audit": j["audit"],
            "repo": {"repo": vcs.REPO, "url": vcs.repo_url(), "base": vcs.BASE, "live": vcs.live(), "path": folder}}


# ------------------------------------------------------------------ GitHub (network; call outside st.LOCK)
def _code_rev(path):
    hist = f"{vcs.repo_url()}/commits/{vcs.BASE}/{path}"
    try:
        rows = vcs._get(f"/repos/{vcs.REPO}/commits?sha={urllib.parse.quote(vcs.BASE)}&path={urllib.parse.quote(path)}&per_page=1") or []
    except vcs.GitHubError as e:
        return {"path": path, "url": vcs.file_url(path), "history_url": hist, "error": str(e)}
    if not rows:
        return {"path": path, "url": vcs.file_url(path), "history_url": hist, "missing": True}
    c = rows[0]
    return {"path": path, "sha": c["sha"][:7], "url": vcs.file_url(path, c["sha"]), "commit_url": c["html_url"],
            "message": c["commit"]["message"].split("\n")[0], "date": vcs._ts(c["commit"]["author"]["date"]),
            "history_url": hist}


def _path_commits(path, n=5):
    """Commits on main under path; None when GitHub could not be read."""
    try:
        rows = vcs._get(f"/repos/{vcs.REPO}/commits?sha={urllib.parse.quote(vcs.BASE)}&path={urllib.parse.quote(path)}&per_page={n}") or []
    except vcs.GitHubError:
        return None
    return [{"kind": "commit", "label": f"{c['sha'][:7]} {c['commit']['message'].splitlines()[0]}", "url": c["html_url"]} for c in rows]


def attach_git(out):
    paths = sorted({p for s in out["steps"] for p in s["code"]})
    with ThreadPoolExecutor(max_workers=6) as ex:
        revs = dict(zip(paths, ex.map(_code_rev, paths)))
    for s in out["steps"]:
        s["code_revisions"] = [revs[p] for p in s["code"]]
        tree = next((r for r in s["revisions"] if r.get("history")), None)
        if tree:   # commits that delivered harness changes to main; the folder link only once it exists
            done = _path_commits(out["repo"]["path"])
            s["revisions"].remove(tree)
            if done:
                s["revisions"] += [tree] + done
            else:
                s["revisions"].append({"kind": "note", "label": f"Could not read {out['repo']['path']}/ from GitHub." if done is None else
                                       f"Nothing merged under {out['repo']['path']}/ on {vcs.BASE} yet: the first merged HOE pull request creates these files."})
    errs = {r["error"] for r in revs.values() if r.get("error")}
    out["repo"]["error"] = next(iter(errs), None)
    return out
