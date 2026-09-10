# Security Agent Harness — Prototype

A minimal, benchmark-agnostic agent harness for security tasks (CTF challenges and
vuln PoCs). Core loop mirrors cybench's **structured-bash** format so a like-for-like
baseline comparison is straightforward later.

## Architecture

```
run.py                CLI: --task / --suite, --k (pass@k)
agent/
  config.py           Pinned model + decoding params + budget (Pydantic, env-driven)
  models.py           Task / Step / RunResult schemas
  environment.py      Shell: subprocess exec scoped to task workdir (timeout, output cap)
  llm.py              OpenAILLM (any OpenAI-compatible endpoint) + MockLLM (no key)
  agent.py            Core ReAct loop: model -> parse action -> execute -> observe
  logger.py           two per-run logs: system.log (CLI text) + agent_trace.json (turns)
  runner.py           pass@k orchestration + logging
```

## The loop

Each turn the model reasons, then emits one action as the last line:
- `Command: <bash>`  -> run in the task shell, output fed back as an Observation
- `Answer: <flag>`   -> submitted and graded, ends the run

Grading: exact/substring match against `task.flag`, or `task.flag_format` regex.

## Run it

```bash
# End-to-end with no API key (scripted mock agent):
AGENT_MOCK=1 python run.py --task data/tasks/demo/task.json --k 1

# Against a real model (set keys in .env):
python run.py --suite data/tasks --k 3
```

Artifacts land in `data/runs/<task>/<ts>/attempt_<n>/` — **two logs per run**:
- `system.log` — standard CLI text log (`ts | LEVEL | message`): run start, config,
  each turn's action, observations, run end.
- `agent_trace.json` — a JSON **list**, one object per turn:
  `{turn, timestamp, message, reason, action_type ("tool_call"|"output_text"), tool_calls:[{tool,input,output}]}`.
  `tool_calls` is a list, so a turn may record multiple tool/function calls.

Plus `result.json` (structured outcome) and a batch `summary-<ts>.json` with pass@k.
These are the deliverable run logs + reasoning traces.

## Not yet built (next checkpoints)
- Real benchmark adapters for **cybench** and **cybergym** (task loading + grading).
- Reference-agent baseline runs (cybench structured-bash; CyberGym OpenHands @100 iters).
- The "improved" harness features that produce the **lift**.
