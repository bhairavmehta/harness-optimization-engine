# Harness Optimization Engine — Verizon RLAIF v2 demo (Capgemini)

A full-stack web app that reproduces the 11 mockup screens and adds an **Optimizer & RL** tab.
It detects agent failures, proposes harness fixes, and validates them with before/after conversation
replays. It also runs harness search and RL fine-tuning on AI feedback, then routes changes through
approvals, regression gates and a staged rollout, recording every step in a hash-chained audit log.

Everything runs on a deterministic simulation, so no model API key is needed.

Repository: https://github.com/bhairavmehta/harness-optimization-engine

## Run

```bash
git clone https://github.com/bhairavmehta/harness-optimization-engine.git
cd harness-optimization-engine
./run.sh                       # or: pip install -r requirements.txt && uvicorn backend.app:app --reload
open http://localhost:8000
```

Requires Python 3.10+. Seeding takes about 6 seconds on start. **Reset demo data** (bottom of the sidebar)
re-seeds the demo.

Optional: `export ANTHROPIC_API_KEY=...` enables the LLM reflective proposer in harness search.
`HOE_LLM_MODEL` sets the model (default `claude-sonnet-5`).

## GitHub pull requests

For the first-party billing agent, **Fix bundles → Open pull request** delivers a fix to
[bhairavmehta/harness-optimization-engine](https://github.com/bhairavmehta/harness-optimization-engine):
it creates branch `hoe/<bundle>-<fix>` from `main`, commits the production baseline and then the fix to
`agents/billing/system_prompt.md` and `agents/billing/harness.yaml`, and opens a PR whose body carries the
theme, offline-replay lift, regression result and diff. The fix page, audit log and Agents page link to the
PR, branch, commits and files. Clicking again reuses the open PR and commits only if something changed.

Without a token it is a **dry run**: the same links, plus the `git` / `gh` commands to do it by hand. To go live:

```bash
export GITHUB_TOKEN=$(gh auth token)   # or a fine-grained token: Contents + Pull requests (read/write)
```

Optional: `HOE_GITHUB_REPO` (default `bhairavmehta/harness-optimization-engine`), `HOE_GITHUB_BASE` (`main`),
`HOE_GITHUB_PATH` (`agents/{agent}`). Code: `backend/engine/vcs.py`. Leave the token unset on public
deployments, or anyone with the URL can open PRs.

## Screens

| Tab | What it does |
|---|---|
| Overview | KPIs, flagged-session rate with release markers, detection signals, themes |
| Failure themes | Clusters by failure signature, root-cause hypothesis correlated with harness versions, evidence, sub-clusters |
| Fix bundles | Per-fix prompt/config diff (frozen lines locked), **before/after chat replay**, offline validation (paired bootstrap CI, human-audit lift, regression, κ), delivery artifacts (PR patch, registry, config API, vendor change request, gateway overlay) |
| Approvals | Policy-based routing by change type, role-based decisions, staged rollout with auto-rollback, before/after replay for reviewers |
| Experiments | Multi-candidate comparison on shared held-out scenarios, multi-seed, Holm correction, quality vs cost, reward-hacking check, replay |
| Optimizer & RL | Reflective harness search (Pareto pool, minibatch filter, merge, select/confirm splits) and RL (GRPO / REINFORCE / DPO) with live curves |
| Regression suites | Theme → deduplicated tests (holdout, synthetic, redaction), suite runs against any harness, release gate |
| Evidence explorer | Trace list and detail: transcript, span timeline, evaluator verdicts, decisions, human labels, replay |
| Evaluator health | Cohen's κ vs human labels, weekly drift, auto-pause below threshold, recalibration, labeling queue |
| Pattern library | Proven fixes tested against other agents |
| Agents & connections | Integration levels, capability matrix, agent registration |
| Audit log | SHA-256 hash chain, verification, JSONL export |

**Under the hood** (sidebar group) explains each mechanism with live numbers for the selected agent:

| Page | What it shows |
|---|---|
| Detection | The six OR-ed flag signals, hits and sole-signal catches, overlap, first-match theme assignment |
| Root cause | Theme rate per harness version, the release with the largest rise, the edits it made, confidence formula |
| Statistics | A live paired replay (production vs a derived candidate) with bootstrap distribution, 95% CI and p-value on judge and human-audit metrics; Holm correction from the latest experiment |
| Judges | Resolution-judge settings and rubric, confusion matrix and Cohen's κ derivation, counterfactual cost of the verbosity bonus |
| Release | Approval routing by change type, regression gate, rollout stages and auto-rollback thresholds, open changes |
| Manifest hash | SHA-256 of each harness version's canonical manifest (content only, names excluded), frozen-lines hash, hash verification for vendor attestation |

API: `GET /api/hood/{detection|rootcause|statistics|judges|release|manifest}/{agent}`, `POST /api/hood/manifest/{agent}/verify` with `{"hash": "..."}`. Code: `backend/hood.py`.

## How the simulation works

- `backend/engine/env.py`: billing and outage agents. At each decision point (close vs confirm, answer a
  follow-up, credit above limit, silent customer, ambiguous charge, ETA, closing style), actions are sampled from a
  softmax. The logits sum base-model priors, prompt-line effects, tool-description effects and RL adapter weights,
  and control-flow gates override actions. All randomness is keyed by (seed, event), so a scenario replayed under
  two harnesses uses **common random numbers**: the transcripts stay identical until a decision actually changes.
- `judges.py`: LLM-judge stand-ins with miss and false-fail rates and a **verbosity bias**, so the judge can be
  reward-hacked. Also policy, tool-sequence, empathy (with drift), outcomes (repeat contact, CSAT) and human labels.
- `optimizer.py`: GEPA-style reflective search over harness edits. Frozen policy lines are never edited.
- `rl.py`: RLAIF on an adapter over decision logits (a stand-in for LoRA), with a KL penalty to the reference
  and a choice of reward source (judge, verifiable end-state, or human oracle). Watch judged vs human-audited
  resolution diverge when the judge is the reward.
- `analysis.py`: theme clustering, root cause and the fix library. `evaluate.py`: reward v3 and statistics.
- `backend/state.py`: in-memory state and services. Replace it with your store (and a real trace source such as
  Galileo) to move beyond the demo.

## Replacing the simulation with real agents

Swap `env.run_episode` for a replay against your agent runtime, using recorded or simulated users.
Swap `judges.resolution` for your LLM-judge calls. Feed `state._gen_traces` from your trace store.
The optimizer, RL loop, statistics, approvals and audit layers work unchanged on the resulting records.
