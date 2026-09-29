"""Harness Optimization Engine — FastAPI backend.

Run:  uvicorn backend.app:app --reload   (from the project root)
"""
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from . import hood, state as st
from .engine import env, harness as H, jobs, llm, vcs

app = FastAPI(title="Harness Optimization Engine", version="1.0")
FRONTEND = Path(__file__).resolve().parent.parent / "frontend"


@app.on_event("startup")
def _startup():
    st.seed()


@app.exception_handler(Exception)
async def _err(request, exc):
    code = 400 if isinstance(exc, (ValueError, KeyError, StopIteration)) else 500
    return JSONResponse({"error": f"{type(exc).__name__}: {exc}"}, status_code=code)


async def body(req: Request):
    try:
        return await req.json()
    except Exception:
        return {}


def locked(fn, *a, **k):
    with st.LOCK:
        return fn(*a, **k)


# ------------------------------------------------------------------ meta
@app.get("/api/bootstrap")
def bootstrap():
    return {"agents": st.agents_view()["items"], "waiting": st.approvals()["waiting"], "llm": llm.available(), "git": vcs.status(),
            "library": {"lines": H.LINES, "gates": H.GATES, "tools": H.TOOLS, "criteria": H.CRITERIA},
            "decisions": env.DECISION_LABEL, "actions": env.ACTION_LABEL}


@app.post("/api/reset")
def reset():
    return locked(st.reset)


# ------------------------------------------------------------------ overview & themes
@app.get("/api/overview/{aid}")
def overview(aid: str, range: str = "7d", start: str = None, end: str = None):
    return locked(st.overview, aid, range, start, end)


@app.post("/api/analysis/{aid}")
def analysis(aid: str):
    return locked(st.analyze, aid, "You")


@app.get("/api/themes/{aid}")
def themes(aid: str):
    return locked(st.themes, aid)


@app.get("/api/theme/{tid}")
def theme(tid: str):
    return locked(st.theme_detail, tid)


# ------------------------------------------------------------------ traces
@app.get("/api/traces/{aid}")
def traces(aid: str, theme: str = None, filter: str = None, limit: int = 60, offset: int = 0):
    return locked(st.trace_list, aid, theme, filter, limit, offset)


@app.get("/api/trace/{tid}")
def trace(tid: str):
    return locked(st.trace_detail, tid)


@app.post("/api/trace/{tid}/label")
async def label(tid: str, req: Request):
    b = await body(req)
    return locked(st.label_trace, tid, b.get("verdict", "Confirmed failure"))


@app.post("/api/trace/{tid}/to-suite")
async def trace_to_suite(tid: str):
    def fn():
        t = st.S["traces"][tid]
        sid = st.S["suite_by_agent"][t["agent"]]
        su = st.S["suites"][sid]
        a = st.TYPE_ASSERTION.get(t["type"], "tool_order")
        test = st._make_test(f"RT-{len(su['tests']) + 101}", t["type"], t["seed"], t["samp"], a, tid)
        su["tests"].append(test)
        st.audit("You", "Trace added to regression suite", sid, f"{tid} → {test['id']}")
        return test
    return locked(fn)


# ------------------------------------------------------------------ harnesses & replay
@app.get("/api/candidates/{aid}")
def candidates(aid: str):
    return locked(st.candidates, aid)


@app.get("/api/harness/{hid}")
def harness(hid: str):
    def fn():
        h = st.get_h(hid)
        base = st.prod(h["agent"])
        return {"harness": H.public(h), "prompt_rows": H.prompt_rows(base, h), "config_rows": H.config_rows(base, h),
                "policy": {d: env.softmax(env.logits(h, d)) for d in env.BASE}, "patch": H.patch(base, h)}
    return locked(fn)


@app.post("/api/replay")
async def replay(req: Request):
    b = await body(req)
    return locked(st.replay, b["base_id"], b["cand_id"], b.get("scen_seed"), b.get("samp_seed"), b.get("trace_id"),
                  b.get("mode", "simulator"), float(b.get("sim_error", 0)))


@app.get("/api/replay-examples")
def replay_examples(base_id: str, cand_id: str, theme: str = None, k: int = 8):
    return locked(st.replay_examples, base_id, cand_id, theme, k)


# ------------------------------------------------------------------ bundles
@app.get("/api/bundles")
def bundles(agent: str = None):
    return locked(st.bundles, agent)


@app.get("/api/bundle/{bid}")
def bundle(bid: str):
    return locked(st.bundle_view, bid)


@app.post("/api/theme/{tid}/bundle")
async def gen_bundle(tid: str, req: Request):
    b = await body(req)
    return locked(st.generate_bundle, tid, "You", True, int(b.get("n", 600)))


@app.get("/api/fix/{bid}/{fid}")
def fix(bid: str, fid: str):
    return locked(st.fix_view, bid, fid)


@app.post("/api/fix/{bid}/{fid}/validate")
async def validate(bid: str, fid: str, req: Request):
    b = await body(req)
    return locked(st.validate_fix, bid, fid, int(b.get("n", 600)), float(b.get("sim_error", 0)), "You")


@app.post("/api/fix/{bid}/{fid}/deliver")
async def deliver(bid: str, fid: str, req: Request):
    b = await body(req)
    return locked(st.delivery, bid, fid, b.get("method", "pr"))


@app.post("/api/fix/{bid}/{fid}/approve-request")
async def fix_to_approval(bid: str, fid: str, req: Request):
    def fn():
        f = next(x for x in st.S["bundles"][bid]["fixes"] if x["id"] == fid)
        h = st._fix_harness(st.S["bundles"][bid], f)
        return st.create_approval(st.S["bundles"][bid]["agent"], h["id"], f["title"], bundle_id=bid, fix_ids=[fid])
    return locked(fn)


# ------------------------------------------------------------------ experiments
@app.get("/api/experiments")
def experiments(agent: str = None):
    return locked(st.experiments, agent)


@app.get("/api/experiment/{eid}")
def experiment(eid: str):
    return locked(lambda: st.S["experiments"][eid])


@app.post("/api/experiments")
async def new_experiment(req: Request):
    b = await body(req)
    return locked(st.run_experiment, b["agent"], b["candidates"], int(b.get("n", 1200)), int(b.get("seeds", 1)),
                  float(b.get("sim_error", 0)), b.get("name"), b.get("theme_id"), b.get("weights"), b.get("id"))


@app.post("/api/experiment/{eid}/promote")
async def promote(eid: str, req: Request):
    b = await body(req)
    def fn():
        e = st.S["experiments"][eid]
        h = st.get_h(b["candidate"])
        return st.create_approval(e["agent"], h["id"], f"{h['name']} (from {eid})")
    return locked(fn)


# ------------------------------------------------------------------ optimizer & RL jobs
@app.post("/api/optimizer/run")
async def run_optimizer(req: Request):
    return locked(st.start_optimizer, await body(req))


@app.post("/api/rl/run")
async def run_rl(req: Request):
    return locked(st.start_rl, await body(req))


@app.get("/api/jobs")
def job_list():
    return [j.view(full=False) for j in jobs.JOBS.values()][::-1]


@app.get("/api/jobs/{jid}")
def job(jid: str):
    return jobs.JOBS[jid].view()


@app.post("/api/jobs/{jid}/cancel")
def cancel(jid: str):
    jobs.JOBS[jid].cancelled = True
    return {"ok": True}


# ------------------------------------------------------------------ regression
@app.get("/api/suites")
def suites(agent: str = None):
    return locked(st.suites, agent)


@app.get("/api/suite/{sid}")
def suite(sid: str):
    return locked(st.suite_detail, sid)


@app.post("/api/suite/{sid}/run")
async def suite_run(sid: str, req: Request):
    b = await body(req)
    return locked(st.run_suite, sid, b["harness_id"], True, bool(b.get("include_holdout")))


@app.post("/api/suite/{sid}/gate")
async def suite_gate(sid: str, req: Request):
    b = await body(req)
    return locked(st.set_gate, sid, b.get("min_pass"), b.get("policy_all"))


@app.post("/api/theme/{tid}/convert")
async def convert(tid: str, req: Request):
    b = await body(req)
    return locked(st.convert_theme, tid, b.get("suite"), int(b.get("max_tests", 64)), float(b.get("holdout", 0.2)),
                  bool(b.get("synthetic", True)), bool(b.get("redact", True)), bool(b.get("commit", False)))


# ------------------------------------------------------------------ approvals
@app.get("/api/approvals")
def approvals():
    return locked(st.approvals)


@app.get("/api/approval/{cid}")
def approval(cid: str):
    return locked(lambda: st.approval_view(st.S["approvals"][cid]))


@app.post("/api/approval/{cid}/decide")
async def decide(cid: str, req: Request):
    b = await body(req)
    return locked(st.decide, cid, b["role"], b["decision"], b.get("comment", ""), b.get("actor"))


@app.post("/api/approval/{cid}/advance")
def advance(cid: str):
    return locked(st.advance, cid)


# ------------------------------------------------------------------ evaluators, patterns, agents, audit
@app.get("/api/evaluators/{aid}")
def evaluators(aid: str):
    return locked(st.evaluators, aid)


@app.post("/api/evaluators/{aid}/{eid}/recalibrate")
def recalibrate(aid: str, eid: str):
    return locked(st.recalibrate, aid, eid)


@app.get("/api/patterns")
def patterns():
    return locked(st.patterns)


@app.post("/api/pattern/{pid}/test")
async def test_pattern(pid: str, req: Request):
    b = await body(req)
    return locked(st.test_pattern, pid, b["target"])


@app.get("/api/agents")
def agents():
    return locked(st.agents_view)


@app.post("/api/agents")
async def register_agent(req: Request):
    b = await body(req)
    return locked(st.register_agent, b["name"], b.get("type", "First-party"), b.get("level", "1p_norepo"),
                  b.get("owner", ""), b.get("traffic", ""))


@app.get("/api/audit")
def audit(actor: str = None, q: str = None):
    rows = st.S["audit"]
    if actor:
        rows = [r for r in rows if r["actor"] == actor]
    if q:
        rows = [r for r in rows if q.lower() in json.dumps(r).lower()]
    return {"items": rows[::-1], "actors": sorted({r["actor"] for r in st.S["audit"]})}


@app.get("/api/audit/verify")
def audit_verify():
    return st.audit_verify()


@app.get("/api/audit/export")
def audit_export():
    return PlainTextResponse("\n".join(json.dumps(r) for r in st.S["audit"]), media_type="application/x-ndjson",
                             headers={"Content-Disposition": "attachment; filename=hoe-audit.jsonl"})


@app.get("/api/lineage/{obj}")
def lineage(obj: str):
    return st.lineage(obj)


# ------------------------------------------------------------------ under the hood
HOOD = {"detection": hood.detection, "rootcause": hood.root_cause, "statistics": hood.statistics,
        "judges": hood.judges_view, "release": hood.release, "manifest": hood.manifests}


@app.get("/api/hood/{section}/{aid}")
def hood_view(section: str, aid: str):
    if section not in HOOD:
        raise HTTPException(404, f"Unknown section {section}")
    return locked(HOOD[section], aid)


@app.post("/api/hood/manifest/{aid}/verify")
async def hood_verify(aid: str, req: Request):
    b = await body(req)
    return locked(hood.verify_hash, aid, b.get("hash"))


# ------------------------------------------------------------------ version control
GIT_EVENTS = ("Pull request", "Version control")


def _vcs_view(force):
    out = vcs.summary(force=force)  # network I/O: deliberately outside st.LOCK
    with st.LOCK:
        out["activity"] = [r for r in st.S["audit"][::-1] if r["event"].startswith(GIT_EVENTS)][:50]
        out["hoe_prs"] = st.S.get("prs", {})
    return out


@app.get("/api/vcs")
def vcs_view():
    return _vcs_view(False)


@app.post("/api/vcs/sync")
def vcs_sync():
    out = _vcs_view(True)
    s = out.get("sync") or {}
    with st.LOCK:
        st.audit("You", "Version control synced", vcs.REPO,
                 out["error"] or f"main @ {out['head']['short']} · " + ("code in sync" if s.get("in_sync") else f"{len(s.get('drift', []))} files differ"))
        out["activity"] = [r for r in st.S["audit"][::-1] if r["event"].startswith(GIT_EVENTS)][:50]
    return out


# ------------------------------------------------------------------ frontend
app.mount("/static", StaticFiles(directory=FRONTEND), name="static")


@app.get("/")
def index():
    return FileResponse(FRONTEND / "index.html")
