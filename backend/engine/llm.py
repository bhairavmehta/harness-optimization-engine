"""Optional LLM reflective proposer (Anthropic Messages API).

Enabled when ANTHROPIC_API_KEY is set and the run requests it. The model reads
failing transcripts and picks one edit from the allowed edit space; frozen lines
are never offered. Falls back to rule-based reflection on any error.
"""
import json
import os
import re
import urllib.request

from . import harness as H

MODEL = os.environ.get("HOE_LLM_MODEL", "claude-sonnet-5")


def available():
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _transcript(rec):
    ep = rec.get("ep")
    if not ep:
        return f"[{rec['type']}] judged_pass={rec['judged_pass']} premature={rec['premature']}"
    lines = []
    for m in ep["messages"]:
        who = m["role"] if m["role"] != "tool" else f"tool:{m['name']}"
        lines.append(f"{who}: {m['text']}")
    return "\n".join(lines)


def propose(h, failing, options):
    if not options:
        return None, ""
    menu = "\n".join(f"{i}. [{H.edit_layer(e)}] {H.edit_label(e)}" for i, e in enumerate(options))
    fails = "\n\n---\n\n".join(_transcript(r) for r in failing) or "(no failing sessions in this minibatch)"
    prompt = (
        "You are the reflective proposer in a harness optimizer for a customer-care agent.\n"
        f"Current system prompt:\n{H.system_prompt(h)}\n\nGates: {h['gates']}\n\n"
        f"Failing sessions from the latest minibatch:\n{fails}\n\n"
        f"Allowed edits (frozen policy lines are not editable):\n{menu}\n\n"
        "Diagnose the most common failure in one or two sentences, then choose exactly one edit.\n"
        'Reply with JSON only: {"reflection": "...", "edit_index": <int>}'
    )
    body = json.dumps({"model": MODEL, "max_tokens": 400,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, headers={
        "content-type": "application/json", "x-api-key": os.environ["ANTHROPIC_API_KEY"],
        "anthropic-version": "2023-06-01"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read())
    text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
    m = re.search(r"\{.*\}", text, re.S)
    parsed = json.loads(m.group(0))
    idx = int(parsed["edit_index"])
    if not 0 <= idx < len(options):
        raise ValueError("edit_index out of range")
    return options[idx], "LLM reflection: " + parsed.get("reflection", "").strip()
