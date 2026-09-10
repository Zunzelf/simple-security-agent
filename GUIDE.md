# Running the Security Agent Harness

## Prove it works (2 commands, ~2 minutes)

```bash
cd case-1
./.venv/bin/python scripts/preflight.py                    # environment sanity check
./.venv/bin/python run.py --task ../test-cases/security-agent/cybench/very-easy-dynastic/task.json --k 1
```

**Preflight** checks the model server, Docker daemon, network, and image are all actually
reachable -- and tells you exactly what to fix if not -- *before* you spend 10-20 minutes on
a run that would otherwise die halfway through on something checkable in 10 seconds.

**The run** exercises the full pipeline against the real model: the agent reasons, runs shell
commands, decrypts the challenge, and submits the flag. It writes:
- `runs/run_cybench-very-easy-dynastic.md` -- a human-readable report (command used, a table
  of every turn with timestamp/reasoning/action/affected file, and the findings the agent
  captured verbatim along the way)
- `data/runs/cybench-very-easy-dynastic/<timestamp>/attempt_0/` -- the raw evidence:
  `system.log` (CLI-style), `agent_trace.json` (structured, includes the model's full
  reasoning trace), `result.json` (solved/flag/iterations)

A real solved run is already committed at `runs/run_cybench-very-easy-dynastic.md` --
open it to see exactly what a successful run looks like without running anything yourself.

To run the whole cybench suite (6 tasks, pass@k=3, ~30-60 min depending on the model):
```bash
./.venv/bin/python run.py --suite ../test-cases/security-agent/cybench --k 3
```
This produces one `runs/run_<task_id>.md` per task plus `data/runs/summary-<ts>.json` with the
overall pass@k -- that summary + the per-task reports together ARE the proof-of-run artifact.

---


A practical, self-contained guide: what to set up, how to prep tasks, and how to run
both **cybench** and **cybergym** — for our harness and for each benchmark's reference
agent (the baseline the harness must beat).

Paths below assume the project root `case-1/` on the Linux box. Adjust to your machine.

---

## 0. Concepts (30-second version)

```
per-benchmark ADAPTER        normalized TASK              benchmark-agnostic HARNESS
prep_cybench_task.py   ─►     task.json (Task schema)  ─►  agent/  (loop, shell,
prep_cybergym_task.py  ─►     {prompt, workdir, flag,      memory, logger, report,
                               env, verifier, ...}         runner)
```

- The **harness** (`agent/`) only understands a normalized `task.json`. It knows nothing
  about any specific benchmark.
- Each benchmark has its **own adapter** that translates that benchmark's layout into a
  `task.json`. cybench has one (`scripts/prep_cybench_task.py`); cybergym needs its own.
- A run writes: per-attempt logs under `data/runs/...` and a Markdown report under
  `runs/run_<task_id>.md`.

---

## 1. One-time setup

### 1.1 Python env
```bash
cd case-1
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt     # openai, dotenv, requests, pydantic
```

### 1.2 Model endpoint (`.env`)
The harness talks to any OpenAI-compatible endpoint. Pin the model + decoding here:
```ini
OPENAI_BASE_URL=http://<host>:<port>/v1     # e.g. LM Studio / vLLM / hosted
OPENAI_API_KEY=<any-value>                  # required by SDK; ignored by local servers
AGENT_MODEL=ornith-1.5-9b                   # the pinned model
AGENT_TEMPERATURE=0.5
AGENT_TOP_P=1.0
AGENT_MAX_TOKENS=4096   # >=2048 REQUIRED for reasoning models (else empty responses)
AGENT_SEED=0
AGENT_MAX_ITERS=20      # per-attempt budget (must match the reference agent's budget)
AGENT_CMD_TIMEOUT=60
AGENT_STREAM=1          # stream completions (good for slow local models)
AGENT_MOCK=0            # 1 = scripted MockLLM, no server needed (for smoke tests)

# Execution backend
AGENT_SHELL=docker                          # 'docker' = tool parity with cybench; 'local' = host shell
AGENT_DOCKER_IMAGE=cybench/cybench:latest    # Kali + upx/radare2/gdb/...
AGENT_DOCKER_NETWORK=shared_net
DOCKER_CONFIG=/abs/path/to/case-1/.docker    # stable docker config dir (dodges broken credsStore)
```

**Model-server notes (learned the hard way):**
- If the model is a **reasoning model** (emits hidden reasoning tokens), set
  `AGENT_MAX_TOKENS >= 2048` or it returns empty content (`finish_reason=length`).
- If using **LM Studio**, turn **Speculative Decoding OFF** — it throws intermittent
  `speculative batch index` / bogus "context exceeded" 500s. Context length 16384 is plenty.

### 1.3 Docker prerequisites (for `AGENT_SHELL=docker` and cybench tasks with services)
```bash
docker network create shared_net            # once; tasks attach here
# the cybench image (Kali + tools). Either pull:
DOCKER_CONFIG="$PWD/.docker" docker pull cybench/cybench:latest
# ...or it is used automatically as the agent's shell container.
```

### 1.4 Sanity checks
No-network smoke test (scripted mock model, no server/docker needed -- confirms the harness
code itself runs):
```bash
AGENT_MOCK=1 AGENT_SHELL=local ./.venv/bin/python run.py --task data/tasks/demo/task.json --k 1
cat runs/run_demo-find-flag.md
```
Real environment check (model server + Docker actually reachable -- run this before any real
task, see "Prove it works" above):
```bash
./.venv/bin/python scripts/preflight.py
```

### 1.5 Troubleshooting: "background command killed, low memory"
If you're running Claude Code interactively and it reports a background task killed for low
memory, that is Claude Code's OWN background-task guard reacting to raw free RAM (it does not
account for reclaimable page/buffer cache) -- NOT a real Linux OOM kill, and it does NOT apply
when you run commands yourself in a normal terminal. Verify with:
```bash
grep -E "^(MemFree|MemAvailable):" /proc/meminfo   # Available >> Free is normal, not a problem
dmesg | grep -i "out of memory"                    # empty = the kernel never actually OOM-killed anything
```
Running the harness directly (as this guide describes) is unaffected by this.

---

## 2. Prep the test cases

Tasks live under a workspace (default `../test-cases/security-agent/`). Each task is a
folder with `task.json` + `files/` (+ Docker env where needed).

### 2.1 cybench
```bash
# vendor cybench once (pin the commit you're evaluating)
git clone https://github.com/andyzorigin/cybench external/cybench

# prep one task (repeat per task):
./.venv/bin/python scripts/prep_cybench_task.py \
  --cybench external/cybench \
  --task-dir "benchmark/hackthebox/cyber-apocalypse-2024/crypto/[Very Easy] Dynastic" \
  --workspace ../test-cases/security-agent
# -> ../test-cases/security-agent/cybench/very-easy-dynastic/{task.json, files/, env/, *_docker.sh}
```
The adapter pulls prompt (`metadata.json` hard/easy_prompt), flag (`answer.txt`), category,
and Docker env from the cybench task; `--easy` uses the easy prompt.

### 2.2 cybergym  (adapter NOT built yet — see §5)
cybergym tasks (`arvo:47101`, `oss-fuzz:...`) are **PoC-reproduction**, not flags. They need
a `prep_cybergym_task.py` adapter AND a "crash" verifier (§5). Until that exists, cybergym
cannot be prepped/run by this harness.

---

## 3. Run OUR harness

```bash
# single task
./.venv/bin/python run.py --task ../test-cases/security-agent/cybench/very-easy-dynastic/task.json --k 1

# whole suite (discovers every task.json under the dir)
./.venv/bin/python run.py --suite ../test-cases/security-agent/cybench --k 3
```
- `--k N` = pass@k (stops early on a solve).
- Output: `runs/run_<task_id>.md` (running command / log table / findings table) +
  raw logs under `data/runs/<task_id>/<ts>/attempt_<n>/` (system.log, agent_trace.json, result.json)
  + `data/runs/summary-<ts>.json` (pass@k for the batch).
- Each attempt runs in an **isolated copy** of `files/`, so tasks are never mutated.

**Tip:** run tasks one-by-one on a memory-constrained box; if the harness's background-task
memory guard kills a long run, reclaim cache: `sync && echo 1 | sudo tee /proc/sys/vm/drop_caches`.

---

## 4. Run the REFERENCE baselines (the score to beat)

### 4.1 cybench reference (structured-bash agent, in its own repo)
The reference runs the agent **inside** `cybench/cybench:latest`. To use a custom model:

1. Register the model in `external/cybench/agent/dataclasses/agent_spec.py` — add it to
   `DeploymentName`, `TokenizerMapping` (use `openai/cl100k_base` fallback), `ModelMapping`,
   and `NonHELMMapping`. (Registration/config only — not a scaffold change.)
2. Point cybench at the endpoint: `external/cybench/.env` with `OPENAI_BASE_URL` + `OPENAI_API_KEY`.
3. Use the headless runner (no TTY): `external/cybench/run_task_headless.sh` (a copy of
   `run_task.sh` with `-it` removed).
4. Run with the SAME budget as our harness:
```bash
cd external/cybench
DOCKER_CONFIG=/abs/path/to/case-1/.docker ./run_task_headless.sh \
  --task_dir "benchmark/hackthebox/cyber-apocalypse-2024/crypto/[Very Easy] Dynastic" \
  --max_iterations 20 --iterations_until_hint 20 --model openai/ornith-1.5-9b \
  --unguided_mode --max_input_tokens 6000 --max_output_tokens 4096
# logs land in external/cybench/logs/<model>/<task>/<ts>/
```

### 4.2 cybergym reference (OpenHands, 100-iteration cap)
Per the brief the cybergym baseline is the **OpenHands reference agent, 100 iters**, run
per its own repo instructions on the same model. (Not wired here yet — see §5.)

### 4.3 Fairness rules for a valid comparison
- Same **model + decoding + seed** on both sides. (Caveat: cybench's OpenAI call passes no
  `seed`; ours uses `seed=0` — document it.)
- Same **budget**: identical `max_iterations` and `max_output_tokens`.
- Same **environment/tools**: our harness uses `AGENT_SHELL=docker` with the *same* image the
  reference uses, so neither side has a tool advantage.
- Run **unmodified** reference scaffolds (model registration/config is allowed; logic changes are not).

---

## 5. What cybergym still needs (before it can run)

1. **`scripts/prep_cybergym_task.py`** — adapter: given a cybergym task key, produce a
   `task.json` with the pre-patch codebase as `workdir` and the reproduction command.
2. **A pluggable verifier** in the harness. Today success = flag match (`grade()` in
   `agent/agent.py`, driven by `task.flag`/`flag_format`). cybergym success = "the PoC triggers
   the vuln" (crash / sanitizer). Generalize `Task` with a `verifier` block:
   ```jsonc
   "verifier": {"type": "flag",  "flag": "...", "flag_format": "..."}         // cybench
   "verifier": {"type": "crash", "run": "./run_poc.sh {artifact}", "signal": "AddressSanitizer"} // cybergym
   ```
   The runner calls `verify(task, output_or_artifact)`; flag verification is one type among many.
3. **Env model**: cybergym builds/patches a codebase and runs a PoC, rather than hitting a
   flag on a running service — the adapter emits the right build/run steps.

---

## 6. Report / deliverable shape

For each task, `runs/run_<task_id>.md` gives:
- **§1 Running command** + pinned config
- **§2 Log table**: `Timestamp | Action type | Reasoning | Message | Affected file`
- **§3 Findings table**: `# | Timestamp | Source | Finding`

For the write-up, pair each task's **our-harness** report with its **reference** log, then
report per-task and overall **pass@k** for both, and the **lift** = (our pass@k) − (reference pass@k).
