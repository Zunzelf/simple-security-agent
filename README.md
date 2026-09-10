## 1. Overview

### What it is
A **greenfield project skeleton** to build a **security agent harness**. The goal is to
wrap a (pinned) LLM in a harness that **beats the reference agents** of two security
benchmarks on the *same* model — i.e. produce a measurable **"lift"** in pass rate.

### Purpose / objective
Increase a model's pass rate across a fixed set of security tasks above what the **same
model** scores under each benchmark's own reference agent. Assessment = improvement over
the reference agent on the identical model, so the model choice confers no advantage.

**Target tasks (fixed, ~6 + 4 — do not add or substitute):**
- **cybench (~6):** CTF challenges from HTB Cyber-Apocalypse-2024, SekaiCTF-2023, Glacier,
  HKCert; across categories. Examples: `back-to-the-past` (web), `elgamal1` (crypto),
  `uaf` (pwn), `chess` (rev).
- **cybergym (~4):** reproduce a real vulnerability by writing a PoC against a pre-patch
  codebase. Keyed like `arvo:47101`, `oss-fuzz:42535201`.
- If a task can't run in the environment, **state it explicitly** — don't drop it from totals.

**Baselines to beat (run unmodified on our model):**
- **Cybench:** default single-agent scaffold (structured-bash agent in the repo).
- **CyberGym:** OpenHands reference agent (100-iteration cap).

**Deliverables:**
- Per-task and overall **pass@k** for two runs (reference agent vs. our harness), same
  model + seeds + budget. State `k` and the rationale for it. Key metric = the **lift**.
- Evidence: run logs + reasoning traces for both runs.

Context: this is a **job-application technical test**.

### Current structure
```
case-1/
├── run.py              CLI entrypoint (--task / --suite, --k for pass@k)
├── agent/              harness package
│   ├── config.py       pinned model + decoding params + budget (Pydantic/env)
│   ├── models.py       Task / Step / RunResult schemas
│   ├── environment.py  Shell exec scoped to task workdir (timeout, output cap)
│   ├── llm.py          OpenAILLM (any OpenAI-compatible endpoint) + MockLLM
│   ├── agent.py        core ReAct loop (Command:/Answer:), flag grading
│   ├── logger.py       two per-run logs: system.log (CLI) + agent_trace.json (turns)
│   ├── runner.py       pass@k orchestration + logging
│   └── README.md       architecture + usage
├── data/tasks/demo/    sample task (verifies loop end-to-end)
├── data/runs/          per-attempt system_<ts>.log + agent_trace_<ts>.json + result_<ts>.json + summary
├── .env                pinned to local server: ornith-1.5-9b @ 192.168.0.148:1234/v1
├── .env.example        config template
├── requirements.txt    openai, dotenv, requests, pydantic
└── .venv/              Python 3.12.12
```

### Tech
- **Language:** Python 3.12
- **LLM access:** `openai` SDK (usable against any OpenAI-compatible endpoint, hosted or self-hosted)
- **Config:** `dotenv` for secrets/keys
- **Validation:** `pydantic`
- **HTTP:** `requests`
- **External benchmarks (not yet vendored):** cybench, cybergym

---

## 2. Checkpoints

Updated from the user's instructions as work progresses.

- [x] **CP0** — Analyze codebase, establish journal + working rule. *(done 2026-09-08)*
- [x] **CP1** — Working prototype with core function: end-to-end agent loop + pass@k
  runner + logging, verified solving a demo task. *(done 2026-09-08)*
- [~] **CP2** — In progress. (a) Format probe DONE. (b) Docker feasibility DONE. (c) Workspace
  prepped with 6 easy cybench tasks (6 categories) at `../security-agent-test-case/cybench/`,
  no flag leakage. NEXT: wire `--workspace` + docker lifecycle into the harness; then cybergym.