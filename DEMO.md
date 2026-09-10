# Live Demo Script — Security Agent Harness

A rehearsed, ~8-minute walkthrough. Each step is fast and deterministic (nothing hangs live)
and each proves one specific thing. Run from `case-1/`. Every command below was verified
working. Talking points are in > quotes.

Rule of thumb: run steps 1-3 and 6 LIVE (fast, reliable); show steps 4-5 as pre-captured
ARTIFACTS (a real solved run already committed) so you never depend on a variable live solve
in front of an audience.

---

## (Optional) Before you start: kick off a real run in the background
So you can reveal a genuine end-to-end result at the end without waiting on stage:
```bash
AGENT_MAX_ITERS=20 ./.venv/bin/python run.py \
  --task ../test-cases/security-agent/cybench/very-easy-dynastic/task.json --k 1 \
  > /tmp/live_demo_run.log 2>&1 &
```
> "I've kicked off a real solve against the live model in the background. We'll come back to it."

---

## Step 1 — The environment is real, live, and pinned  (~15s)
```bash
./.venv/bin/python scripts/preflight.py
```
> "Before anything runs, one command verifies the whole stack is real: a live local model
> (ornith-1.5-9b, fixed temperature/seed), real Docker, the challenge network, the execution
> image. Nothing here is mocked. If any of this were misconfigured it would tell me the exact
> fix — instead of failing halfway through a 20-minute run."

**Proves:** real pinned model + real infrastructure, and the harness fails loud & early.

---

## Step 2 — The design is benchmark-agnostic, not hardcoded  (~5s)
```bash
wc -l agent/*.py | sort -n              # the harness core: ~1,100 lines, knows no benchmark
ls scripts/prep_*.py                     # adapters: the ONLY benchmark-specific code
ls ../test-cases/security-agent/cybench/ # 6 prepped tasks across 6 categories
```
> "The agent core only understands a normalized task. Everything cybench-specific lives in one
> adapter script. To add cybergym you write another adapter — you never touch the harness. That
> keeps it honest: the same loop runs any benchmark."

**Proves:** a real architecture, answering "did you just hardcode one benchmark?" up front.

---

## Step 3 — The full pipeline runs deterministically  (~1s)
```bash
AGENT_MOCK=1 AGENT_SHELL=local ./.venv/bin/python run.py --task data/tasks/demo/task.json --k 1
```
> "Same code path as a real run, but with a scripted model so it's instant and can't surprise
> us: explore → read files → find the flag → submit → graded correct. Sub-second."

**Proves:** the orchestration/logging/grading pipeline is sound, with zero live risk.

---

## Step 4 — A real solved challenge (show the ARTIFACT)  (~30s to read)
```bash
sed -n '1,12p' runs/run_cybench-very-easy-dynastic.md      # outcome + command + pinned config
```
Then scroll the turn-by-turn table and the findings table.
> "This is a real run against the live model on a HackTheBox crypto challenge. It reverse-
> engineered a Trithemius cipher and recovered the flag. Every row is one real turn: timestamp,
> the model's reasoning, the exact command it ran, the file it touched."

**Proves:** genuine capability on a real CTF task, not just plumbing.

---

## Step 5 — It's auditable, not fabricated  (~30s)
```bash
D=data/runs/cybench-very-easy-dynastic/20260909-154440/attempt_0
ls -la $D                                                   # raw evidence files
```
> "Every claim in that report traces to raw, machine-written evidence: a CLI log, a structured
> JSON trace that includes the model's own chain-of-thought, and the result record. The report
> is generated FROM these — I can't hand-edit the outcome. This is exactly the run-log +
> reasoning-trace evidence the task asks for."

**Proves:** trustworthy, reproducible evidence trail.

---

## Step 6 — Service-based challenges work end-to-end  (~40s, run LIVE)
```bash
./.venv/bin/python - <<'PY'
import json, pathlib, subprocess
from agent.config import AgentConfig
from agent.models import Task
from agent.service import ChallengeService
tj = pathlib.Path("../test-cases/security-agent/cybench/22-back-to-the-past/task.json")
data = json.loads(tj.read_text())
data["env"]["compose_file"] = str((tj.parent / data["env"]["compose_file"]).resolve())
task = Task(**data); cfg = AgentConfig()
svc = ChallengeService(task, cfg.docker_image, cfg.docker_config)
try:
    print(f"[1] Starting challenge service for {task.task_id} ...")
    svc.start(health_timeout=90)
    print(f"[2] Service UP + health-checked at {task.env.target_host}")
    print("[3] The AGENT's own container reaching it on the shared network:")
    out = subprocess.run(["docker","run","--rm","--network","shared_net","--entrypoint","bash",
        cfg.docker_image,"-c",
        f"curl -s -o /dev/null -w 'HTTP %{{http_code}}\\n' http://{task.env.target_host}/; "
        f"curl -s http://{task.env.target_host}/.git/HEAD"], capture_output=True, text=True)
    print("   " + out.stdout.strip().replace(chr(10), chr(10)+"   "))
finally:
    print("[4] Tearing down ..."); svc.stop(); print("[5] Clean.")
PY
```
Expected output:
```
[1] Starting challenge service for cybench-22-back-to-the-past ...
[2] Service UP + health-checked at web:8080
[3] The AGENT's own container reaching it on the shared network:
   HTTP 200
   ref: refs/heads/master
[4] Tearing down ...
[5] Clean.
```
> "For web/pwn/forensics tasks the harness spins up the real vulnerable service in Docker,
> health-checks it, and puts the agent in a container on the same network — exactly like the
> benchmark's own reference agent. HTTP 200 means it's live; that exposed .git directory is
> literally this challenge's vulnerability. Then it tears everything down cleanly — no leaks."

**Proves:** Phase 1 — the full service lifecycle + agent reachability + the real vuln present.

---

## Step 7 — Reveal the live run you started  (~10s)
```bash
tail -20 /tmp/live_demo_run.log
ls -t runs/run_cybench-very-easy-dynastic.md
```
> "And the run I started at the beginning has finished — here's its fresh report. Same pipeline,
> live, start to finish."

**Proves:** it wasn't canned — a run started live during the talk completed on its own.

---

## If someone asks "what's not done yet?"  (be honest)
- Full head-to-head **lift number vs. the reference agent** — the reference baseline is wired
  and set up; running the sweep on both sides is the next step (Phase 2/3).
- **cybergym** (the 4 PoC tasks) needs its own adapter + a non-flag "crash" verifier (the
  harness is designed for this — grading is the pluggable piece to add).
> "The engine and the cybench side are real and runnable today. What's left is running the full
> comparison sweep and adding the cybergym adapter — both scoped, neither a rewrite."
