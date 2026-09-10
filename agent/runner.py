"""Run orchestration: pass@k over tasks, plus logging of traces and run logs.

Writes, per attempt, under data/runs/<task_id>/<timestamp>/attempt_<n>/:
  - trace.jsonl : one JSON line per step (reasoning trace + action + observation)
  - run.log     : human-readable log
  - result.json : structured RunResult (solved, flag, iterations, config)
And a summary.json aggregating pass@k for the batch.
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from .config import AgentConfig
from .agent import Agent
from .llm import build_llm
from .logger import RunLogger
from .report import write_report
from .service import ChallengeService, ServiceError
from .models import Task, RunResult

RUNS_DIR = Path("data/runs")


def _write_result(run_dir: Path, res: RunResult, stamp: str) -> Path:
    """Structured outcome. The two run logs are written live by RunLogger."""
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / f"result_{stamp}.json"
    with path.open("w") as f:
        json.dump(res.model_dump(), f, indent=2)
    return path


def run_task(task: Task, cfg: AgentConfig, k: int = 1) -> dict:
    """Run k attempts of a task; return pass@k record.

    If the task needs a challenge service (env.type == "docker-compose"), it is brought up
    ONCE for the whole task (not per attempt -- this mirrors how cybench's own run_task.sh
    invocation covers a single agent run against one service instance) and always torn down,
    even on crash.
    """
    if task.env.type == "docker-compose" and cfg.shell_backend != "docker":
        # A local shell can't resolve the service's container-DNS address (e.g. "web:8080"),
        # so a task that needs a service would silently fail every attempt. Fail fast instead.
        raise RuntimeError(
            f"{task.task_id} requires a running challenge service (target_host="
            f"{task.env.target_host!r}) but AGENT_SHELL={cfg.shell_backend!r}. "
            f"Set AGENT_SHELL=docker so the agent's shell shares the service's network."
        )

    llm = build_llm(cfg)
    agent = Agent(llm, cfg)
    ts = time.strftime("%Y%m%d-%H%M%S")
    base = RUNS_DIR / task.task_id / ts
    attempts: list[RunResult] = []

    service = ChallengeService(task, cfg.docker_image, cfg.docker_config)
    try:
        service.start()
    except ServiceError as e:
        print(f"[service] FAILED to start for {task.task_id}: {e}")
        return {
            "task_id": task.task_id, "benchmark": task.benchmark, "category": task.category,
            "k": k, "attempts_used": 0, "solved": False, "flag": None,
            "run_dir": str(base), "error": f"service_error: {e}",
        }
    if service.is_up:
        print(f"[service] up for {task.task_id} (target_host={task.env.target_host})")

    try:
        for a in range(k):
            run_dir = base / f"attempt_{a}"
            stamp = f"{ts}-a{a}"
            # Isolate the run: the agent works in a fresh COPY of the task files so it can never
            # mutate the prepped task (and each pass@k attempt starts from identical state).
            run_task_obj = task
            src = Path(task.workdir)
            if src.is_dir():
                wd = run_dir / "workdir"
                wd.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(src, wd, dirs_exist_ok=True)
                run_task_obj = task.model_copy(update={"workdir": str(wd.resolve())})
            logger = RunLogger(run_dir, stamp=stamp)
            logger.run_start(task.task_id, a, cfg.describe())
            try:
                res = agent.solve(run_task_obj, attempt=a, logger=logger)
            except Exception as e:  # backstop: never lose a run to an unexpected crash
                logger.error(f"run crashed: {e}")
                res = RunResult(task_id=task.task_id, attempt=a, solved=False,
                                iterations=0, reason=f"crash: {e}", config=cfg.describe())
            logger.run_end(res.model_dump())
            result_path = _write_result(run_dir, res, stamp)
            trace_path = logger.agent_path
            logger.log_saved({"result_json": result_path})
            logger.close()
            report_path = write_report(task.task_id, trace_path, res.model_dump(),
                                       {"system_log": logger.system_path,
                                        "agent_trace": trace_path,
                                        "result_json": result_path})
            print(f"[report] {report_path}")
            attempts.append(res)
            if res.solved:
                break  # pass@k: solved within k attempts
    finally:
        service.stop()
    solved = any(r.solved for r in attempts)
    return {
        "task_id": task.task_id,
        "benchmark": task.benchmark,
        "category": task.category,
        "k": k,
        "attempts_used": len(attempts),
        "solved": solved,
        "flag": next((r.submitted_flag for r in attempts if r.solved), None),
        "run_dir": str(base),
    }


def run_suite(tasks: list[Task], cfg: AgentConfig, k: int = 1) -> dict:
    records = [run_task(t, cfg, k=k) for t in tasks]
    n = len(records)
    solved = sum(1 for r in records if r["solved"])
    summary = {
        "k": k,
        "num_tasks": n,
        "solved": solved,
        "pass_at_k": (solved / n) if n else 0.0,
        "config": cfg.describe(),
        "tasks": records,
    }
    out = RUNS_DIR / f"summary-{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w") as f:
        json.dump(summary, f, indent=2)
    summary["summary_file"] = str(out)
    return summary
