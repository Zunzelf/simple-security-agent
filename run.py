#!/usr/bin/env python3
"""CLI entrypoint for the security agent harness.

Examples:
  python run.py --task data/tasks/demo/task.json
  python run.py --suite data/tasks --k 3
  AGENT_MOCK=1 python run.py --task data/tasks/demo/task.json   # no API key needed
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from agent.config import AgentConfig
from agent.models import Task
from agent.runner import run_task, run_suite


def load_task(path: Path) -> Task:
    data = json.loads(path.read_text())
    # Resolve workdir relative to the task file if not absolute.
    wd = Path(data["workdir"])
    if not wd.is_absolute():
        wd = (path.parent / wd).resolve()
    data["workdir"] = str(wd)
    env = data.get("env") or {}
    if env.get("compose_file"):
        cf = Path(env["compose_file"])
        if not cf.is_absolute():
            cf = (path.parent / cf).resolve()
        env["compose_file"] = str(cf)
        data["env"] = env
    return Task(**data)


def discover_tasks(root: Path) -> list[Task]:
    return [load_task(p) for p in sorted(root.rglob("task.json"))]


def main() -> None:
    ap = argparse.ArgumentParser(description="Security agent harness")
    ap.add_argument("--task", type=Path, help="path to a single task.json")
    ap.add_argument("--suite", type=Path, help="dir to discover task.json files under")
    ap.add_argument("--k", type=int, default=1, help="attempts per task (pass@k)")
    args = ap.parse_args()

    cfg = AgentConfig()
    print("[harness] config:", json.dumps(cfg.describe()))

    if args.task:
        rec = run_task(load_task(args.task), cfg, k=args.k)
        print(json.dumps(rec, indent=2))
    elif args.suite:
        summary = run_suite(discover_tasks(args.suite), cfg, k=args.k)
        print(json.dumps({k: v for k, v in summary.items() if k != "tasks"}, indent=2))
        for t in summary["tasks"]:
            print(f"  [{'PASS' if t['solved'] else 'FAIL'}] {t['task_id']} "
                  f"({t['benchmark']}/{t['category']})")
    else:
        ap.error("provide --task or --suite")


if __name__ == "__main__":
    main()
