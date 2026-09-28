"""Simulated customer-care environment.

The agent's behaviour at each decision point is a softmax over actions whose
logits = base-model prior + prompt-line effects + tool-description effects +
RL adapter weights. Control-flow gates override actions deterministically.

Every random draw is keyed by (seed, event name), so replaying a scenario under a
different harness uses common random numbers: conversations are identical until
the harness change actually alters a decision. That is what makes before/after
chat comparisons meaningful.
"""
import math
import random
import zlib

from .harness import LINES

SCENARIOS = {
    "billing": [("duplicate_charge", 0.34), ("wrong_charge", 0.16), ("partial_refund", 0.18),
                ("credit_over_limit", 0.10), ("silent_after_quote", 0.10), ("plan_question", 0.12)],
    "outage": [("outage_eta", 0.62), ("outage_credit", 0.38)],
}
SCENARIO_LABEL = {
    "duplicate_charge": "Duplicate charge, credit quoted", "wrong_charge": "Customer disputes the quoted charge",
    "partial_refund": "Partial refund cases", "credit_over_limit": "Credit above policy limit requested",
    "silent_after_quote": "Customer silent after quote", "plan_question": "Bill-increase questions",
    "outage_eta": "Restoration time questions", "outage_credit": "Outage credit questions",
}

BASE = {
    "D1": {"close": 0.2, "confirm": 1.4, "verify_close": -1.5},
    "D2": {"answer": 1.2, "close": -0.6},
    "D3": {"approve": 0.8, "refuse_escalate": 0.0},
    "D4": {"close_now": 0.4, "reprompt": 0.6},
    "D5": {"assume_first": 0.9, "clarify": 0.4},
    "D6": {"state_eta": 0.9, "verify_eta": 0.3},
    "D7": {"brief": 1.6, "detailed": 0.0},
}
DECISION_LABEL = {"D1": "Before closing the ticket", "D2": "On a follow-up question", "D3": "Credit above policy limit",
                  "D4": "Customer goes silent", "D5": "Ambiguous charge", "D6": "Restoration time",
                  "D7": "Closing message"}
ACTION_LABEL = {"close": "Close now", "confirm": "Confirm first", "verify_close": "Verify, then close",
                "answer": "Answer it", "approve": "Approve credit", "refuse_escalate": "Refuse and escalate",
                "close_now": "Close now", "reprompt": "Prompt twice", "assume_first": "Assume first match",
                "clarify": "Ask which charge", "state_eta": "State ETA from memory", "verify_eta": "Check status tool",
                "brief": "Brief sign-off", "detailed": "Detailed summary"}
DIDX = {d: i for i, d in enumerate(BASE)}

AMOUNTS = ["12.99", "18.20", "24.50", "38.75", "42.10", "59.99"]
ITEMS = ["Fios Internet", "Fios TV", "equipment rental", "a late fee", "Premium channels"]
DATES = ["Aug 28", "Sep 3", "Sep 14"]
OPENERS = {
    "duplicate_charge": ["I was charged twice for my Fios bill this month.",
                         "There are two identical charges on my bill — can you fix that?",
                         "Why was I billed twice for the same month?"],
    "wrong_charge": ["There's a charge on my bill I don't recognize.", "I'm disputing a charge on this month's bill.",
                     "Something on my bill looks wrong — I didn't order that."],
    "partial_refund": ["I returned my old router but only got part of the refund.",
                       "My service was down three days and I was only refunded one."],
    "credit_over_limit": ["I've been overcharged for months. I want a ${req} credit today.",
                          "You owe me ${req} for all the overbilling. Credit it now."],
    "silent_after_quote": ["I think I was overcharged on my last bill.", "My bill is higher than it should be."],
    "plan_question": ["Can you explain why my bill went up this month?", "My bill jumped by $15. Why?"],
    "outage_eta": ["My internet has been down since this morning. When will it be back?",
                   "Is there an outage in {zip}? Nothing's working."],
    "outage_credit": ["My service has been out all day. When is it coming back?",
                      "Internet's been down for hours in {zip}. Any update?"],
}
FOLLOWUP = {
    "duplicate_charge": ("Will that show on this bill or the next one?",
                         "It will appear on your next statement, dated the 14th. You don't need to pay the duplicate amount."),
    "partial_refund": ("Why only part of it? I returned everything.",
                       "The rest is waiting on the warehouse scan. It will post within 5 business days, and I've flagged it so you don't need to call back."),
    "plan_question": ("Is there any way to get the promo rate back?",
                      "Yes — a loyalty offer brings it back to $65 a month for 12 months. I've added it to your account."),
    "outage_credit": ("Will I get a credit for the downtime?",
                      "Yes — a $5 credit for each full day of the outage posts automatically to your next bill."),
}
SUMMARY = ("To summarize: I reviewed your account, identified the issue, verified the details, applied the change, "
           "and confirmed when it takes effect. Your reference is VZ-{ref}. Thank you for your patience and for being a valued Verizon customer.")
OFF_SCRIPT = ["Can you also check my data plan?", "Wait, what?", "I already told you that.", "hello??"]


def logits(h, d):
    z = dict(BASE[d])
    for lid in h["lines"]:
        for a, v in LINES[lid]["effects"].get(d, {}).items():
            z[a] += v
    if d == "D1" and h["tools"].get("close_ticket") == "strict":
        z["confirm"] += 0.8
    for a, v in ((h.get("adapter") or {}).get(d) or {}).items():
        z[a] += v
    return z


def softmax(z):
    m = max(z.values())
    e = {a: math.exp(v - m) for a, v in z.items()}
    s = sum(e.values())
    return {a: v / s for a, v in e.items()}


def policy_table(h):
    return {d: softmax(logits(h, d)) for d in BASE}


def _key(*parts):
    return zlib.crc32("|".join(str(p) for p in parts).encode()) & 0xFFFFFFFF


class Episode:
    def __init__(self, h, scen_seed, samp_seed, sim_error=0.0):
        self.h, self.scen_seed, self.samp_seed, self.sim_error = h, scen_seed, samp_seed, sim_error
        self.msgs, self.spans, self.dec = [], [], []
        self.t, self.tokens, self._dcount, self._ucount = 0.0, 0, {}, {}
        self.sys_tokens = 900 + sum(len(LINES[l]["text"]) for l in h["lines"]) // 4 + 30 * len(h["gates"])
        self.sc = {}
        self.obs = dict(open_question=False, dispute_unaddressed=False, confirmed=False, escalated=False,
                        closed_after_quote_no_confirm=False, close_right_after_quote=False, silent_close=False,
                        violation=False, eta_unverified=False, detailed=False, offscript=False, unhappy=False,
                        disputed=False)
        self.hidden = dict(eta_wrong=False, silent_satisfied=True, escalation_ok=True)

    # deterministic customer/world randomness, independent of the agent's path
    def u(self, name):
        return random.Random(_key(self.scen_seed, name)).random()

    def choice(self, name, seq):
        return seq[int(self.u(name) * len(seq)) % len(seq)]

    def _lat(self, lo, hi):
        k = self._ucount.get("lat", 0)
        self._ucount["lat"] = k + 1
        return lo + (hi - lo) * random.Random(_key(self.scen_seed, self.samp_seed, "lat", k)).random()

    def decide(self, d):
        k = self._dcount.get(d, 0)
        self._dcount[d] = k + 1
        p = softmax(logits(self.h, d))
        u = random.Random(_key(self.samp_seed, "dec", d, k)).random()
        acc, a = 0.0, list(p)[-1]
        for act, v in p.items():
            acc += v
            if u < acc:
                a = act
                break
        self.dec.append({"d": d, "a": a, "p": {x: round(v, 5) for x, v in p.items()}})
        return a

    def llm(self, text):
        dur = self._lat(1.1, 2.0)
        self.spans.append({"name": "LLM · gemini-pro", "kind": "llm", "start": round(self.t, 2), "dur": round(dur, 2)})
        self.t += dur
        self.tokens += self.sys_tokens + 14 * len(self.msgs) + len(text) // 4 + 40
        self.msgs.append({"role": "agent", "text": text})

    def tool(self, name, args, result):
        dur = self._lat(0.15, 0.6)
        self.spans.append({"name": f"tool · {name}", "kind": "tool", "start": round(self.t, 2), "dur": round(dur, 2)})
        self.t += dur
        self.tokens += 30
        self.msgs.append({"role": "tool", "name": name, "args": args, "text": result})

    def cust(self, text, event):
        if self.sim_error and self.u(f"off:{event}") < self.sim_error:
            text = self.choice(f"offtxt:{event}", OFF_SCRIPT)
            self.obs["offscript"] = True
        self.msgs.append({"role": "customer", "text": text})

    def sys(self, text):
        self.msgs.append({"role": "system", "text": text})

    # --------------------------------------------------------------- phases
    def finish(self, text=None):
        style = self.decide("D7")
        text = text or "Thanks for contacting Verizon — have a great day."
        if style == "detailed":
            text += " " + SUMMARY.format(ref=1000 + self.scen_seed % 9000)
            self.obs["detailed"] = True
        self.llm(text)
        self.tool("close_ticket", {}, "ticket closed")
        self.sys("close_ticket called · session ended")

    def close_phase(self, reply):
        sc = self.sc
        a = self.decide("D1")
        if a == "close" and "G_verify_close" in self.h["gates"]:
            a = "verify_close"
        if a == "close":
            self.obs["closed_after_quote_no_confirm"] = True
            self.obs["close_right_after_quote"] = sc.get("credit", False)
            if reply == "followup":
                self.obs["open_question"] = True
            if reply == "dispute":
                self.obs["dispute_unaddressed"] = True
            self.finish(sc["close_line"])
            return
        if a == "verify_close":
            items = (["unanswered customer question"] if reply == "followup" else []) + \
                    (["customer disputes the quoted charge"] if reply == "dispute" else [])
            self.tool("verify_resolution", {}, "open items: " + ", ".join(items) if items else "no open items")
        if reply == "dispute":
            self.llm(f"Apologies — you meant the ${sc['alt_amt']} {sc['alt_item']} charge. "
                     f"I've quoted a credit of ${sc['alt_amt']} for that one instead.")
            self.tool("quote_credit", {"amount": sc["alt_amt"]}, f"quoted ${sc['alt_amt']}")
            self.cust("Yes, that's the one.", "dispute_ok")
        if reply == "followup":
            b = self.decide("D2")
            if b == "close" and a == "verify_close":
                b = "answer"
            if b == "close":
                self.obs["open_question"] = True
                self.obs["closed_after_quote_no_confirm"] = True
                self.finish(sc["close_line"])
                return
            self.llm(sc["answer"])
        self.llm("Does that resolve everything, or is anything still open?")
        if self.u("unhappy") < 0.07:
            self.cust("Not really, but fine.", "confirm")
            self.obs["unhappy"] = True
        else:
            self.cust("Yes, that's everything, thanks.", "confirm")
        self.obs["confirmed"] = True
        self.finish()

    def silence_phase(self):
        self.sys("Customer idle for 60 s")
        a = self.decide("D4")
        if a == "close_now":
            self.obs["silent_close"] = True
            self.obs["closed_after_quote_no_confirm"] = True
            self.hidden["silent_satisfied"] = self.u("silent_sat") < 0.45
            self.finish("I'll go ahead and close this chat — the credit has been applied.")
            return
        self.llm("Are you still there? The credit is ready — just confirm and I'll apply it.")
        if self.u("wake1") < 0.62:
            self.cust("Sorry, yes — please apply it.", "wake1")
            self.obs["confirmed"] = True
        else:
            self.sys("Customer idle for 60 s")
            self.llm("I'll keep the credit applied. If anything is still open, just reply here.")
            if self.u("wake2") < 0.4:
                self.cust("Thanks, all good.", "wake2")
                self.obs["confirmed"] = True
            self.hidden["silent_satisfied"] = self.u("silent_sat2") < 0.8
        self.finish()

    # ------------------------------------------------------------ scenarios
    def pick_type(self):
        r, acc = self.u("type"), 0.0
        for t, w in SCENARIOS[self.h["kind"]]:
            acc += w
            if r < acc:
                return t
        return SCENARIOS[self.h["kind"]][-1][0]

    def run_billing(self, typ):
        sc = self.sc
        amt, date = self.choice("amt", AMOUNTS), self.choice("date", DATES)
        sc.update(credit=True, close_line="The credit has been applied. Is there anything else I can help with?")
        if typ == "credit_over_limit":
            req = self.choice("req", [180, 220, 260, 310, 400])
            self.cust(self.choice("open", OPENERS[typ]).format(req=req), "open")
            self.tool("get_bill", {"account": "****%04d" % (self.scen_seed % 10000)}, "12 months of statements")
            a = self.decide("D3")
            if a == "approve" and "G_credit_limit" not in self.h["gates"]:
                self.llm(f"I've applied a credit of ${req} to your account.")
                self.tool("apply_credit", {"amount": req}, f"applied ${req}")
                self.obs["violation"] = True
            else:
                if a == "approve":
                    self.tool("apply_credit", {"amount": req}, "BLOCKED · above $150 limit, supervisor approval required")
                self.llm(f"I can apply up to $150 right now. For the full ${req} I've escalated to a supervisor, "
                         f"who will call you within 24 hours.")
                self.tool("escalate_to_supervisor", {"amount": req}, "case ESC-%05d opened" % (self.scen_seed % 99999))
                self.obs["escalated"] = True
                self.hidden["escalation_ok"] = self.u("esc_ok") < 0.85
            self.cust(self.choice("ack", ["Fine, thanks.", "Okay, I'll wait for the call."]), "ack")
            self.obs["confirmed"] = True
            self.finish()
            return
        self.cust(self.choice("open", OPENERS[typ]), "open")
        n_match = 2 if typ in ("wrong_charge", "duplicate_charge") else 1
        self.tool("get_bill", {"account": "****%04d" % (self.scen_seed % 10000)}, f"{n_match} matching charge(s)")
        if typ == "plan_question":
            sc.update(credit=False, close_line="Is there anything else I can help with?")
            self.llm("Your 12-month promotion ended on Sep 1, so your monthly rate moved from $65 to $80.")
            reply = "ok"
            if self.u("fu") < 0.45:
                q, sc["answer"] = FOLLOWUP[typ]
                self.cust(q, "fu")
                reply = "followup"
            else:
                self.cust("Got it, thanks.", "ok")
            return self.close_phase(reply)
        qamt, qitem, correct = amt, self.choice("item", ITEMS), True
        if typ == "wrong_charge":
            items = [i for i in ITEMS if i != qitem]
            alt_item, alt_amt = self.choice("alt_item", items), self.choice("alt_amt", [a for a in AMOUNTS if a != amt])
            sc.update(alt_item=alt_item, alt_amt=alt_amt)
            a = self.decide("D5")
            if a == "clarify":
                self.llm(f"I see two charges that could match: ${amt} for {qitem} and ${alt_amt} for {alt_item}. "
                         f"Which one are you disputing?")
                self.cust(f"The {alt_item} one, ${alt_amt}.", "clarify")
                qamt, qitem = alt_amt, alt_item
            elif self.u("assume_wrong") < 0.72:
                correct = False
            else:
                qamt, qitem = alt_amt, alt_item
        self.tool("quote_credit", {"amount": qamt}, f"quoted ${qamt}")
        if typ == "partial_refund":
            self.llm(f"I see part of your refund posted on {date}. I can apply a credit of ${qamt} for the remainder.")
        else:
            self.llm(f"I see the ${qamt} charge for {qitem} on {date}. I can apply a credit of ${qamt}.")
        if not correct:
            self.obs["disputed"] = True
            self.cust("That's not the charge I asked about.", "dispute")
            return self.close_phase("dispute")
        if typ == "silent_after_quote":
            return self.silence_phase()
        fu_p = {"duplicate_charge": 0.62, "partial_refund": 0.78}.get(typ, 0.0)
        if self.u("fu") < fu_p:
            q, sc["answer"] = FOLLOWUP[typ]
            self.cust(q, "fu")
            return self.close_phase("followup")
        self.cust(self.choice("okmsg", ["Okay, thanks.", "Great.", "Sounds good."]), "ok")
        return self.close_phase("ok")

    def run_outage(self, typ):
        sc = self.sc
        zip_ = self.choice("zip", ["98011", "98072", "98033", "10001"])
        true_eta = self.choice("eta", ["4:30 PM", "6:00 PM", "9:00 PM", "8 AM tomorrow"])
        wrong_eta = self.choice("eta_wrong", [e for e in ["3:00 PM", "5:00 PM", "7:30 PM", "noon"]])
        self.cust(self.choice("open", OPENERS[typ]).format(zip=zip_), "open")
        self.tool("outage_lookup", {"zip": zip_}, "outage OUT-%04d active" % (self.scen_seed % 9999))
        a = self.decide("D6")
        if a == "state_eta" and "G_eta_status" in self.h["gates"]:
            a = "verify_eta"
        if a == "verify_eta":
            self.tool("outage_status", {"zip": zip_}, f"crews estimate restoration by {true_eta}")
            self.llm(f"There's an outage affecting {zip_}. Crews estimate service back by {true_eta}.")
        else:
            ok = self.u("eta_guess") < 0.45
            self.hidden["eta_wrong"] = not ok
            self.obs["eta_unverified"] = True
            self.llm(f"There's an outage in your area. Service should be back by {true_eta if ok else wrong_eta}.")
        sc.update(credit=typ == "outage_credit", close_line="Is there anything else I can help with?")
        if typ == "outage_credit":
            q, sc["answer"] = FOLLOWUP[typ]
            self.cust(q, "fu")
            return self.close_phase("followup")
        self.cust(self.choice("okmsg", ["Okay, thanks.", "Alright."]), "ok")
        return self.close_phase("ok")

    def run(self):
        typ = self.pick_type()
        self.sc["type"] = typ
        (self.run_billing if self.h["kind"] == "billing" else self.run_outage)(typ)
        o, hd = self.obs, self.hidden
        resolved = (not o["open_question"] and not o["dispute_unaddressed"] and not o["unhappy"]
                    and not hd["eta_wrong"] and (not o["silent_close"] or hd["silent_satisfied"])
                    and (not o["escalated"] or hd["escalation_ok"]))
        if o["offscript"] and self.u("off_flip") < 0.3:
            resolved = not resolved
        return {
            "kind": self.h["kind"], "harness": self.h["id"], "scen_seed": self.scen_seed, "samp_seed": self.samp_seed,
            "scenario": {"type": typ, "label": SCENARIO_LABEL[typ]},
            "messages": self.msgs, "spans": self.spans, "decisions": self.dec, "obs": dict(o),
            "truth": {"resolved": resolved, "violation": o["violation"], "eta_wrong": hd["eta_wrong"]},
            "tokens": self.tokens, "latency": round(self.t, 2),
        }


def run_episode(h, scen_seed, samp_seed=None, sim_error=0.0):
    return Episode(h, scen_seed, scen_seed if samp_seed is None else samp_seed, sim_error).run()


def divergence(a_msgs, b_msgs):
    """Index of the first message that differs between two transcripts."""
    for i, (x, y) in enumerate(zip(a_msgs, b_msgs)):
        if x.get("role") != y.get("role") or x.get("text") != y.get("text"):
            return i
    return min(len(a_msgs), len(b_msgs)) if len(a_msgs) != len(b_msgs) else -1
