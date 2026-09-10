"""Per-run Markdown report: runs/run_<task_id>.md

Three sections, as specified:
  1. Running command  - how the run was invoked (plus pinned config)
  2. Log table        - timestamp | action type | reasoning | message | affected file
  3. Findings table   - the working-memory findings with timestamps
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPORTS_DIR = Path("runs")

# Files touched by a command: redirect targets + path-looking tokens.
_REDIR = re.compile(r"(?:>>?|<)\s*([\w./~-]+)")
_PATHY = re.compile(r"(?<![\w/.-])((?:\./|/)?[\w-]+(?:/[\w.-]+)*\.[A-Za-z0-9]{1,6})")


def affected_files(command: str) -> str:
    if not command:
        return ""
    found: list[str] = []
    for m in _REDIR.findall(command):
        if m not in found:
            found.append(m)
    for m in _PATHY.findall(command):
        if m not in found:
            found.append(m)
    return ", ".join(found[:4])


def _cell(text: str, limit: int) -> str:
    """Make a value safe for a Markdown table cell."""
    if not text:
        return ""
    t = " ".join(str(text).split())          # collapse newlines/whitespace
    t = t.replace("|", "\\|").replace("`", "'")
    if len(t) > limit:
        t = t[: limit - 1] + "…"
    return t


def write_report(task_id: str, trace_path: Path, result: dict,
                 log_paths: dict | None = None) -> Path:
    turns = json.loads(Path(trace_path).read_text()) if Path(trace_path).exists() else []
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORTS_DIR / f"run_{task_id}.md"

    cmd = "python " + " ".join(sys.argv) if sys.argv else "(unknown)"
    cfg = result.get("config", {})
    solved = result.get("solved")

    L: list[str] = []
    L.append(f"# Run report — `{task_id}`\n")
    L.append(f"**Outcome:** {'✅ SOLVED' if solved else '❌ not solved'} · "
             f"reason: `{result.get('reason')}` · iterations: {result.get('iterations')} · "
             f"submitted: `{result.get('submitted_flag')}`\n")

    # --- 1. Running command ---
    L.append("## 1. Running command\n")
    L.append("```bash")
    L.append(cmd)
    L.append("```\n")
    if cfg:
        L.append("**Pinned config:** " + ", ".join(
            f"`{k}={v}`" for k, v in cfg.items() if k != "base_url") + "\n")

    # --- 2. Log table ---
    L.append("## 2. Log\n")
    L.append("| Timestamp | Action type | Reasoning | Message | Affected file |")
    L.append("|---|---|---|---|---|")
    for t in turns:
        atype = "tool call" if t.get("action_type") == "tool_call" else "output text"
        # prefer the parsed Thought; fall back to the model's chain-of-thought
        reasoning = t.get("reason") or t.get("reasoning") or ""
        calls = t.get("tool_calls") or []
        if calls:
            for c in calls:
                L.append(f"| {t.get('timestamp','')} | {atype} | {_cell(reasoning,160)} | "
                         f"{_cell(c.get('input',''),120)} | {_cell(affected_files(c.get('input','')),60)} |")
        else:
            L.append(f"| {t.get('timestamp','')} | {atype} | {_cell(reasoning,160)} | "
                     f"{_cell(t.get('message',''),120)} |  |")
    if not turns:
        L.append("| — | — | (no turns recorded) | | |")
    L.append("")

    # --- 3. Findings ---
    L.append("## 3. Findings\n")
    findings = result.get("findings") or []
    L.append("| # | Timestamp | Source | Finding |")
    L.append("|---|---|---|---|")
    for i, f in enumerate(findings, 1):
        src = "flag/auto (verbatim)" if f.get("source") == "auto" else "note (model)"
        L.append(f"| {i} | {f.get('timestamp','')} | {src} | {_cell(f.get('text',''),200)} |")
    if not findings:
        L.append("| — | — | — | (no findings recorded) |")
    L.append("")

    if log_paths:
        L.append("---\n**Raw evidence:** " + " · ".join(
            f"`{k}`: `{v}`" for k, v in log_paths.items()) + "\n")

    out.write_text("\n".join(L))
    return out
