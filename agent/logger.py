"""Two run logs, emitted for every run (attempt).

Format 1 - system.log (CLI text):
    a standard system log, one line per event:  `YYYY-MM-DD HH:MM:SS | LEVEL | message`
    Records run start, pinned config, each turn's action, observations, and run end.

Format 2 - agent_trace.json (JSON list):
    a JSON array with one object PER TURN, tracking the agent itself:
      {
        "turn": 0,
        "timestamp": "2026-09-08T18:20:00",
        "message": "...",                      # the agent's output text this turn
        "reason": "...",                        # the agent's reasoning
        "action_type": "tool_call" | "output_text",
        "tool_calls": [                         # list -> a turn may call many tools
          {"tool": "bash", "input": "ls -la", "output": "..."}
        ]
      }
"""
from __future__ import annotations

import json
import time
from pathlib import Path

SYS_OBS_CAP = 500  # keep the CLI log readable; full output stays in agent_trace.json


class RunLogger:
    def __init__(self, run_dir: str | Path, stamp: str | None = None,
                 to_console: bool = True):
        self.dir = Path(run_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        # A simplified, sortable timestamp embedded in every filename so each run's
        # files stay unique and self-identifying even when collected together.
        self.stamp = stamp or time.strftime("%Y%m%d-%H%M%S")
        self.system_path = self.dir / f"system_{self.stamp}.log"
        self.agent_path = self.dir / f"agent_trace_{self.stamp}.json"
        self._sys = self.system_path.open("w")
        self._turns: list[dict] = []          # Format 2 accumulates here
        self.to_console = to_console

    # ---------- Format 1: system.log (CLI text lines) ----------
    def log(self, level: str, msg: str) -> None:
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        line = f"{ts} | {level:<5} | {msg}"
        self._sys.write(line + "\n")
        self._sys.flush()
        if self.to_console:
            print(line)

    def info(self, msg: str) -> None:  self.log("INFO", msg)
    def debug(self, msg: str) -> None: self.log("DEBUG", msg)
    def warn(self, msg: str) -> None:  self.log("WARN", msg)
    def error(self, msg: str) -> None: self.log("ERROR", msg)

    # ---------- Format 2: agent_trace.json (list of turns) ----------
    def add_turn(self, turn: int, message: str, reason: str,
                 action_type: str, tool_calls: list[dict], reasoning: str = "") -> None:
        record = {
            "turn": turn,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "message": message,
            "reason": reason,
            "reasoning": reasoning,          # full model chain-of-thought (reasoning trace)
            "action_type": action_type,      # "tool_call" | "output_text"
            "tool_calls": tool_calls,        # [{tool, input, output}, ...]
        }
        self._turns.append(record)
        self._flush_agent()

        # Mirror the turn into the CLI system log.
        if action_type == "tool_call":
            for tc in tool_calls:
                self.info(f"turn {turn}: tool_call {tc.get('tool')}: {tc.get('input')}")
                out = str(tc.get("output", ""))
                if len(out) > SYS_OBS_CAP:
                    out = out[:SYS_OBS_CAP] + " ...[truncated]"
                self.debug(f"turn {turn}: output: {out}")
        else:
            self.info(f"turn {turn}: output_text: {message}")

    def _flush_agent(self) -> None:
        with self.agent_path.open("w") as f:
            json.dump(self._turns, f, indent=2)

    # ---------- lifecycle ----------
    def run_start(self, task_id: str, attempt: int, config: dict) -> None:
        self.info(f"run_start | task={task_id} attempt={attempt}")
        self.info(f"config | {json.dumps(config)}")

    def run_end(self, result: dict) -> None:
        self.info(f"run_end | solved={result.get('solved')} "
                  f"reason={result.get('reason')} iters={result.get('iterations')} "
                  f"flag={result.get('submitted_flag')}")

    def log_saved(self, extra: dict | None = None) -> None:
        """Announce, at the end of the run, exactly where this run's files were saved."""
        saved = {
            "system_log": str(self.system_path),
            "agent_trace": str(self.agent_path),
        }
        if extra:
            saved.update({k: str(v) for k, v in extra.items()})
        self.info("run files saved:")
        for name, path in saved.items():
            self.info(f"  - {name}: {path}")

    def close(self) -> None:
        self._flush_agent()
        self._sys.close()
