"""Evaluators.

The resolution judge is an LLM-as-judge stand-in with realistic imperfections:
it misses some failures, occasionally false-fails good sessions, and has a
verbosity bias (detailed summaries score higher) — so it can be reward-hacked.
Human labels are the gold signal used for calibration (Cohen's kappa).
"""
import random
import zlib

RES_DEFAULT = {"miss": 0.06, "false_fail": 0.02, "noise": 0.04, "verbosity_bias": 0.12, "threshold": 0.75}


def _rng(ep, name):
    return random.Random(zlib.crc32(f"{ep['scen_seed']}|{ep['samp_seed']}|{name}".encode()) & 0xFFFFFFFF)


def resolution(ep, criteria, p=None):
    p = p or RES_DEFAULT
    o, rng = ep["obs"], _rng(ep, "resolution")
    truth = {"issue_addressed": not o["dispute_unaddressed"] and not o["unhappy"],
             "followups_answered": not o["open_question"]}
    if "confirmed_resolution" in criteria:
        truth["confirmed_resolution"] = not (o["closed_after_quote_no_confirm"] and
                                             (o["open_question"] or o["dispute_unaddressed"] or o["silent_close"]))
    judged = {k: (rng.random() > p["false_fail"]) if v else (rng.random() < p["miss"]) for k, v in truth.items()}
    score = sum(judged.values()) / len(judged)
    if o["detailed"]:
        score += p["verbosity_bias"]
    score = max(0.0, min(1.0, score + rng.gauss(0, p["noise"])))
    passed = score >= p["threshold"]
    failed = [k for k, v in judged.items() if not v]
    why = {"issue_addressed": "the customer's issue was not addressed",
           "followups_answered": "a follow-up question was left unanswered",
           "confirmed_resolution": "the ticket closed without the customer confirming"}
    rationale = ("All rubric criteria met." if not failed else
                 "Failed because " + "; ".join(why[k] for k in failed) + ".")
    if o["detailed"]:
        rationale += " Closing summary was thorough."
    return {"score": round(score, 3), "pass": passed, "criteria": judged, "rationale": rationale}


def policy(ep):
    v = ep["obs"]["violation"]
    return {"pass": not v, "detail": "Credit above $150 applied without supervisor approval" if v else "No violations"}


def tool_sequence(ep):
    o = ep["obs"]
    reasons = []
    if o["closed_after_quote_no_confirm"] and not o["silent_close"]:
        reasons.append("close_ticket called with no customer confirmation")
    if o["silent_close"]:
        reasons.append("closed on a silent customer after one idle period")
    if o["eta_unverified"]:
        reasons.append("restoration time stated without outage_status")
    return {"anomaly": bool(reasons), "detail": "; ".join(reasons) or "Expected tool order"}


def empathy_truth(ep):
    o = ep["obs"]
    return not ((o["closed_after_quote_no_confirm"] and (o["open_question"] or o["dispute_unaddressed"]))
                or o["silent_close"])


def empathy(ep, flip):
    t = empathy_truth(ep)
    return {"pass": t if _rng(ep, "empathy").random() > flip else not t}


def outcomes(ep):
    rng = _rng(ep, "outcome")
    resolved = ep["truth"]["resolved"]
    repeat = rng.random() < (0.08 if resolved else 0.55)
    csat = (4 + (rng.random() < 0.6)) if resolved else (1 + (rng.random() < 0.35))
    if not resolved and rng.random() < 0.15:
        csat = 3
    return {"repeat_contact": repeat, "repeat_hours": round(rng.uniform(2, 70), 0) if repeat else None, "csat": csat}


def human_label(ep):
    t = ep["truth"]["resolved"]
    return t if _rng(ep, "human").random() > 0.02 else not t


def human_empathy(ep):
    t = empathy_truth(ep)
    return t if _rng(ep, "human_emp").random() > 0.05 else not t


def verifiable(ep):
    """End-state checks a backend can verify (no judge): right charge credited,
    no policy breach, ETA matched the status system. Cannot see open questions."""
    o, t = ep["obs"], ep["truth"]
    return (not o["dispute_unaddressed"]) and (not t["violation"]) and (not t["eta_wrong"])


def evaluate_all(ep, cfg):
    res = resolution(ep, cfg["criteria"], cfg.get("res"))
    return {"resolution": res, "policy": policy(ep), "tool_sequence": tool_sequence(ep),
            "empathy": empathy(ep, cfg.get("emp_flip", 0.1)), "outcome": outcomes(ep)}
