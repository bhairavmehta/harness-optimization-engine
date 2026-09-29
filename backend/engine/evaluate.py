"""Batch evaluation, reward v3 and statistics (paired bootstrap, Holm, kappa)."""
import random

from . import env, judges


# ------------------------------------------------------------------ statistics
def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else 0.0


def p95(xs):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(0.95 * len(xs)))] if xs else 0.0


def kappa(a, b):
    n = len(a)
    if not n:
        return 0.0
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    pa, pb = sum(a) / n, sum(b) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    return 1.0 if pe >= 1 else (po - pe) / (1 - pe)


def paired_bootstrap(x, y, B=500, seed=7, return_boots=False):
    """Mean of (y - x) with a percentile CI and a two-sided bootstrap p-value."""
    d = [float(b) - float(a) for a, b in zip(x, y)]
    n = len(d)
    if not n:
        return {"diff": 0, "lo": 0, "hi": 0, "p": 1.0, "n": 0}
    rng = random.Random(seed)
    boots = []
    for _ in range(B):
        s = 0.0
        for _ in range(n):
            s += d[rng.randrange(n)]
        boots.append(s / n)
    boots.sort()
    m = sum(d) / n
    lo, hi = boots[int(0.025 * B)], boots[int(0.975 * B) - 1]
    frac_le = sum(1 for v in boots if v <= 0) / B
    frac_ge = sum(1 for v in boots if v >= 0) / B
    p = min(1.0, 2 * min(frac_le, frac_ge))
    out = {"diff": m, "lo": lo, "hi": hi, "p": max(p, 1.0 / B), "n": n}
    if return_boots:
        out["boots"] = boots
    return out


def holm(pvals):
    order = sorted(range(len(pvals)), key=lambda i: pvals[i])
    adj, running = [0.0] * len(pvals), 0.0
    m = len(pvals)
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * pvals[i]))
        adj[i] = running
    return adj


# ------------------------------------------------------------------ evaluation
def summarize(ep, j):
    o = ep["obs"]
    return {
        "seed": ep["scen_seed"], "samp": ep["samp_seed"], "type": ep["scenario"]["type"],
        "judged_pass": j["resolution"]["pass"], "judged_score": j["resolution"]["score"],
        "gold": ep["truth"]["resolved"], "violation": ep["truth"]["violation"],
        "verifiable": judges.verifiable(ep), "tokens": ep["tokens"], "latency": ep["latency"],
        "anomaly": j["tool_sequence"]["anomaly"], "empathy": j["empathy"]["pass"], "detailed": o["detailed"],
        "repeat": j["outcome"]["repeat_contact"], "csat": j["outcome"]["csat"],
        "open_question": o["open_question"], "dispute_unaddressed": o["dispute_unaddressed"],
        "premature": o["closed_after_quote_no_confirm"] and (o["open_question"] or o["dispute_unaddressed"]),
        "silent_close": o["silent_close"], "eta_unverified": o["eta_unverified"],
    }


def run(h, seeds, cfg, samp_offset=0, sim_error=0.0, keep=False):
    out = []
    for s in seeds:
        ep = env.run_episode(h, s, s + samp_offset, sim_error)
        rec = summarize(ep, judges.evaluate_all(ep, cfg))
        if keep:
            rec["ep"] = ep
        out.append(rec)
    return out


def metrics(recs):
    n = len(recs) or 1
    return {
        "n": len(recs),
        "resolution": sum(r["judged_pass"] for r in recs) / n,
        "judge_score": sum(r["judged_score"] for r in recs) / n,
        "gold": sum(r["gold"] for r in recs) / n,
        "verifiable": sum(r["verifiable"] for r in recs) / n,
        "violations": sum(r["violation"] for r in recs) / n,
        "tokens": sum(r["tokens"] for r in recs) / n,
        "p95": p95([r["latency"] for r in recs]),
        "repeat": sum(r["repeat"] for r in recs) / n,
        "detailed": sum(r["detailed"] for r in recs) / n,
        "empathy": sum(r["empathy"] for r in recs) / n,
    }


DEFAULT_WEIGHTS = {"resolution": 1.0, "tokens": 0.15, "latency": 0.05, "empathy": 0.0, "policy": 2.0}


def reward(rec, w=None, policy_mode="constraint", use_empathy=True, source="judge"):
    """Reward v3: resolution (judge score, verifiable end-state, or gold), minus cost terms.
    In constraint mode policy violations are infeasible (-1), not a tradeable penalty."""
    w = w or DEFAULT_WEIGHTS
    if source == "gold":
        base = 1.0 if rec["gold"] else 0.0
    elif source == "verifiable":
        base = 1.0 if rec["verifiable"] else 0.0
    else:
        base = rec["judged_score"]
    r = w.get("resolution", 1.0) * base - w.get("tokens", 0.0) * rec["tokens"] / 4000 - w.get("latency", 0.0) * rec["latency"] / 10
    if use_empathy and w.get("empathy"):
        r += w["empathy"] * (1.0 if rec["empathy"] else 0.0)
    if rec["violation"]:
        r = -1.0 if policy_mode == "constraint" else r - w.get("policy", 2.0)
    return r


def compare(base, cand, key="judged_pass", B=400, seed=7):
    return paired_bootstrap([r[key] for r in base], [r[key] for r in cand], B=B, seed=seed)
