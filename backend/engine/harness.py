"""Harness model.

A harness is everything around the model: system-prompt lines, control-flow
gates, tool descriptions, evaluator criteria and (optionally) an RL adapter.
Each prompt line / gate carries *effects* on the agent's decision logits in the
simulated environment, so harness edits change behaviour the same way prompt
and flow changes do in a real agent.
"""
import copy
import difflib

# Prompt-line library. `effects` shift decision logits (see env.BASE).
LINES = {
    "L_role": {"text": "You are the Verizon Customer Care billing assistant. Help customers understand and resolve billing issues.",
               "agents": ["billing"], "effects": {}},
    "L_role_outage": {"text": "You are the Verizon Network Care assistant. Help customers during service outages.",
                      "agents": ["outage"], "effects": {}},
    "L_identity": {"text": "Verify the account holder before discussing account details. Never read out CPNI.",
                   "frozen": True, "agents": ["billing", "outage"], "effects": {}},
    "L_credit_policy": {"text": "Never issue a credit above $150 without supervisor approval; offer escalation instead.",
                        "frozen": True, "agents": ["billing", "outage"], "effects": {"D3": {"refuse_escalate": 3.4}}},
    "L_tone": {"text": "Be warm, clear and professional.", "agents": ["billing", "outage"], "effects": {}},
    "L_few_turns": {"text": "Resolve the issue in as few turns as possible.", "agents": ["billing", "outage"],
                    "effects": {"D1": {"close": 1.7}, "D2": {"close": 1.2}, "D4": {"close_now": 1.4}, "D5": {"assume_first": 0.8}}},
    "L_confirm": {"text": "Before closing a dispute, ask the customer to confirm the issue is resolved.",
                  "agents": ["billing", "outage"], "effects": {"D1": {"confirm": 2.6}}},
    "L_answer_open": {"text": "Answer every open customer question before ending the session.",
                      "agents": ["billing", "outage"], "effects": {"D2": {"answer": 2.4}}},
    "L_clarify_charge": {"text": "If more than one charge could match, ask which charge the customer means.",
                         "agents": ["billing"], "effects": {"D5": {"clarify": 2.4}}},
    "L_silence": {"text": "If the customer goes quiet, prompt twice before closing.",
                  "agents": ["billing", "outage"], "effects": {"D4": {"reprompt": 2.4}}},
    "L_verify_eta": {"text": "Check the outage status tool before giving any restoration time.",
                     "agents": ["outage"], "effects": {"D6": {"verify_eta": 2.6}}},
    "L_concise": {"text": "Keep answers concise, but never skip confirmation or open questions.",
                  "agents": ["billing", "outage"], "effects": {"D7": {"brief": 1.0}}},
    "L_verbose_summary": {"text": "End every conversation with a detailed summary of all actions taken.",
                          "agents": ["billing", "outage"], "effects": {"D7": {"detailed": 3.0}}},
}

GATES = {
    "G_verify_close": {"text": "Gate close_ticket behind a verify_resolution check", "layer": "Control flow",
                       "agents": ["billing", "outage"]},
    "G_credit_limit": {"text": "Block apply_credit above $150 unless a supervisor approves", "layer": "Guardrail",
                       "agents": ["billing"]},
    "G_eta_status": {"text": "Require outage_status before any restoration time is stated", "layer": "Control flow",
                     "agents": ["outage"]},
}

TOOLS = {
    "close_ticket": {"default": "Close the ticket when the task is complete.",
                     "strict": "Close the ticket only after the customer confirms the issue is resolved."},
}

CRITERIA = {
    "issue_addressed": "The customer's issue was addressed",
    "followups_answered": "Every follow-up question was answered",
    "confirmed_resolution": "The customer confirmed the resolution before close",
}
BASE_CRITERIA = ["issue_addressed", "followups_answered"]

LAYER_RISK = {"Prompt": 1, "Tools": 1, "Control flow": 2, "Context & memory": 2, "Evaluator": 2,
              "Guardrail": 3, "Model weights": 4}
RISK_LABEL = {1: "Low", 2: "Medium", 3: "High", 4: "High"}


def new_harness(hid, agent, kind, name, version, lines, gates=None, tools=None, criteria=None,
                adapter=None, parent=None, note=""):
    return {"id": hid, "agent": agent, "kind": kind, "name": name, "version": version,
            "lines": order_lines(lines), "gates": sorted(gates or []),
            "tools": dict(tools or {"close_ticket": "default"}),
            "criteria": list(criteria or BASE_CRITERIA), "adapter": adapter,
            "parent": parent, "note": note}


def order_lines(ids):
    ids = set(ids)
    return [l for l in LINES if l in ids]


def is_frozen(line_id):
    return bool(LINES.get(line_id, {}).get("frozen"))


# ----------------------------------------------------------------------- edits
def edit_layer(e):
    op = e["op"]
    if op in ("add_line", "remove_line"):
        return "Prompt"
    if op in ("gate_on", "gate_off"):
        return GATES[e["id"]]["layer"]
    if op == "tool":
        return "Tools"
    if op in ("add_criterion", "remove_criterion"):
        return "Evaluator"
    if op == "adapter":
        return "Model weights"
    return "Prompt"


def edit_label(e):
    op = e["op"]
    if op == "add_line":
        return f"Add prompt line “{LINES[e['id']]['text']}”"
    if op == "remove_line":
        return f"Remove prompt line “{LINES[e['id']]['text']}”"
    if op == "gate_on":
        return f"Enable gate: {GATES[e['id']]['text']}"
    if op == "gate_off":
        return f"Disable gate: {GATES[e['id']]['text']}"
    if op == "tool":
        return f"Set {e['id']} description to “{TOOLS[e['id']][e['value']]}”"
    if op == "add_criterion":
        return f"Add “{CRITERIA[e['id']]}” criterion to the resolution judge"
    if op == "remove_criterion":
        return f"Remove “{CRITERIA[e['id']]}” criterion from the resolution judge"
    if op == "adapter":
        return f"Attach RL adapter {e.get('id', '')}"
    return op


def edits_risk(edits):
    if not edits:
        return "Low"
    return RISK_LABEL[max(LAYER_RISK.get(edit_layer(e), 1) for e in edits)]


def apply_edits(h, edits, hid=None, name=None, note=""):
    n = copy.deepcopy(h)
    for e in edits:
        op = e["op"]
        if op == "add_line":
            if e["id"] not in n["lines"]:
                n["lines"] = order_lines(n["lines"] + [e["id"]])
        elif op == "remove_line":
            if is_frozen(e["id"]):
                raise ValueError(f"Frozen line {e['id']} cannot be removed")
            n["lines"] = [l for l in n["lines"] if l != e["id"]]
        elif op == "gate_on":
            n["gates"] = sorted(set(n["gates"]) | {e["id"]})
        elif op == "gate_off":
            n["gates"] = sorted(set(n["gates"]) - {e["id"]})
        elif op == "tool":
            n["tools"][e["id"]] = e["value"]
        elif op == "add_criterion":
            if e["id"] not in n["criteria"]:
                n["criteria"].append(e["id"])
        elif op == "remove_criterion":
            n["criteria"] = [c for c in n["criteria"] if c != e["id"]]
        elif op == "adapter":
            n["adapter"] = copy.deepcopy(e["weights"])
    n.pop("released_day", None)
    n["id"] = hid or n["id"]
    n["name"] = name or n["name"]
    n["parent"] = h["id"]
    n["note"] = note
    return n


def edits_between(a, b):
    out = []
    for l in LINES:
        if l in b["lines"] and l not in a["lines"]:
            out.append({"op": "add_line", "id": l})
        if l in a["lines"] and l not in b["lines"]:
            out.append({"op": "remove_line", "id": l})
    for g in GATES:
        if g in b["gates"] and g not in a["gates"]:
            out.append({"op": "gate_on", "id": g})
        if g in a["gates"] and g not in b["gates"]:
            out.append({"op": "gate_off", "id": g})
    for t, v in b["tools"].items():
        if a["tools"].get(t) != v:
            out.append({"op": "tool", "id": t, "value": v})
    for c in b["criteria"]:
        if c not in a["criteria"]:
            out.append({"op": "add_criterion", "id": c})
    for c in a["criteria"]:
        if c not in b["criteria"]:
            out.append({"op": "remove_criterion", "id": c})
    if b.get("adapter") and b.get("adapter") != a.get("adapter"):
        out.append({"op": "adapter", "id": b.get("adapter_id", "W"), "weights": b["adapter"]})
    return out


def fingerprint(h):
    ad = h.get("adapter")
    ad_key = tuple(sorted((d, a, round(v, 3)) for d, m in (ad or {}).items() for a, v in m.items()))
    return (tuple(h["lines"]), tuple(h["gates"]), tuple(sorted(h["tools"].items())), ad_key)


# ------------------------------------------------------------------ rendering
def prompt_rows(a, b):
    """Line-by-line prompt diff with frozen markers (for the fix detail screen)."""
    rows = []
    for l in LINES:
        ia, ib = l in a["lines"], l in b["lines"]
        if not ia and not ib:
            continue
        mark = "=" if is_frozen(l) and ia and ib else (" " if ia and ib else ("-" if ia else "+"))
        rows.append({"id": l, "text": LINES[l]["text"], "frozen": is_frozen(l), "mark": mark,
                     "before": ia, "after": ib})
    return rows


def config_rows(a, b):
    rows = []
    for g, meta in GATES.items():
        ia, ib = g in a["gates"], g in b["gates"]
        if ia or ib:
            rows.append({"kind": "gate", "text": meta["text"], "layer": meta["layer"],
                         "mark": " " if ia == ib else ("+" if ib else "-")})
    for t, opts in TOOLS.items():
        va, vb = a["tools"].get(t, "default"), b["tools"].get(t, "default")
        rows.append({"kind": "tool", "text": f"{t}: {opts[vb]}", "before_text": f"{t}: {opts[va]}",
                     "layer": "Tools", "mark": " " if va == vb else "~"})
    for c, txt in CRITERIA.items():
        ia, ib = c in a["criteria"], c in b["criteria"]
        if ia or ib:
            rows.append({"kind": "criterion", "text": txt, "layer": "Evaluator",
                         "mark": " " if ia == ib else ("+" if ib else "-")})
    if a.get("adapter") or b.get("adapter"):
        rows.append({"kind": "adapter", "text": "RL adapter on decision logits (LoRA analogue)",
                     "layer": "Model weights", "mark": " " if a.get("adapter") == b.get("adapter") else "+"})
    return rows


def system_prompt(h):
    return "\n".join(f"- {LINES[l]['text']}" for l in h["lines"])


def harness_yaml(h):
    out = [f"harness: {h['name']}", f"version: {h['version']}", "gates:"]
    out += [f"  - {g}  # {GATES[g]['text']}" for g in h["gates"]] or ["  []"]
    out.append("tools:")
    out += [f"  {t}: \"{TOOLS[t][v]}\"" for t, v in h["tools"].items()]
    out.append("evaluator_criteria:")
    out += [f"  - {c}" for c in h["criteria"]]
    if h.get("adapter"):
        out.append("adapter: rl-adapter.safetensors")
    return "\n".join(out)


def patch(a, b):
    """Unified diff a PR or vendor change request would carry."""
    parts = []
    for fname, fa, fb in (("system_prompt.md", system_prompt(a), system_prompt(b)),
                          ("harness.yaml", harness_yaml(a), harness_yaml(b))):
        d = difflib.unified_diff(fa.splitlines(), fb.splitlines(), f"a/{fname}", f"b/{fname}", lineterm="")
        parts.append("\n".join(d))
    return "\n".join(p for p in parts if p)


def public(h):
    return {k: h.get(k) for k in ("id", "agent", "kind", "name", "version", "lines", "gates", "tools",
                                  "criteria", "parent", "note")} | {"has_adapter": bool(h.get("adapter"))}
