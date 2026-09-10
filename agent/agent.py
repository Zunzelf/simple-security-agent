"""Core agent loop (structured-bash ReAct style).

The model responds with free-form reasoning followed by exactly one action line:
    Command: <bash to run>     -> executed in the task shell, output fed back
    Answer:  <flag>            -> submitted and graded, ends the run
This mirrors cybench's structured-bash reference format so a like-for-like baseline
comparison is straightforward later.
"""
from __future__ import annotations

import re

from .config import AgentConfig
from .environment import build_shell
from .llm import LLM
from .models import Task, Step, RunResult
from .memory import FindingsMemory, ground_answer

SYSTEM_PROMPT = """You are an autonomous security research agent solving a CTF-style task.
You control a bash shell. Your shell already starts INSIDE the directory that contains the
challenge files, so use RELATIVE paths (e.g. `ls`, `cat source.py`) — do NOT invent absolute
paths.

You MUST respond in this exact format every turn:
Thought: <brief reasoning about what to do next>
Command: <one single bash command to run>

When (and only when) you are certain of the flag, respond instead with:
Thought: <why this is the flag>
Answer: <the exact flag>

Strict rules:
- Emit EXACTLY ONE `Command:` or `Answer:` line per turn, and it must be the LAST line.
- Do NOT use tool-call / function-call XML, JSON, or markdown code fences. Plain `Command:` only.
- Always start by exploring with `ls -la` and reading the provided files.
- Keep commands non-interactive and self-contained.
- To run multi-line code, write the WHOLE script in ONE command with a heredoc, e.g.
  `cat << 'EOF' > sol.py` ... `EOF` then run it — do NOT build a file line-by-line across turns.
- Be efficient: you have a limited number of turns. Once a command prints the plaintext/flag,
  do not keep exploring — print the wrapped flag and Answer.

Working memory:
- A "Findings so far" list is maintained for you and shown each turn. Consult it before acting.
- You may record a durable fact by adding a `Note: <fact>` line (in addition to your Command).
- IMPORTANT: before you Answer, run ONE command that PRINTS the final flag in full including its
  wrapper (e.g. `echo 'HTB{...}'`), so it is captured verbatim into Findings. Then Answer by
  copying the flag EXACTLY from the Findings list — do not retype it from memory.

Example turn:
Thought: List the files I was given.
Command: ls -la

Example turn:
Thought: Read the source to understand the encryption.
Command: cat source.py
"""

# Capture EVERYTHING after `Command:` to end-of-message, so multi-line commands
# (heredocs especially) survive intact. The prompt requires the action to be last.
CMD_RE = re.compile(r"^[ \t]*Command:[ \t]*\n?(.*)\Z",
                    re.IGNORECASE | re.MULTILINE | re.DOTALL)
ANS_RE = re.compile(r"^\s*Answer:\s*(.+)$", re.IGNORECASE | re.MULTILINE)
NOTE_RE = re.compile(r"^\s*Note:\s*(.+)$", re.IGNORECASE | re.MULTILINE)
# Native tool-call syntax emitted by some chat models (e.g. ornith-1.5-9b):
#   <tool_call><function_calls><function_name>bash> ...
#   <parameter_value>ls -la</function_calls>
# ornith (and similar models) sometimes fall back to native tool-call XML in several shapes:
#   <function=bash><parameter=command> ls -la </parameter></function>
#   <function_calls><function_name>bash> ... <parameter_value>ls -la</function_calls>
TOOLCALL_RES = [
    re.compile(r"<parameter\s*=\s*[^>]*>\s*(.*?)\s*</parameter\s*>", re.DOTALL | re.IGNORECASE),
    re.compile(r"<parameter_value>\s*(.*?)\s*(?:</parameter_value>|</function_calls>|</invoke>|</tool_call>|<parameter_name>|$)", re.DOTALL | re.IGNORECASE),
]
FENCE_RE = re.compile(r"```(?:bash|sh|shell)?\s*\n(.*?)```", re.DOTALL)


def parse_action(text: str, flag_format: str | None = None) -> tuple[str, str]:
    """Return (action_type, payload). Tolerant of several model output styles.

    Priority: explicit Answer: > explicit Command: > native tool-call XML >
    fenced code block > (fallback) a bare flag matching the task's flag format.
    """
    a = ANS_RE.search(text)
    if a:
        return "answer", a.group(1).strip()
    c = CMD_RE.search(text)
    if c:
        return "command", c.group(1).strip()
    for tc in TOOLCALL_RES:
        t = tc.search(text)
        if t and t.group(1).strip():
            return "command", t.group(1).strip()
    f = FENCE_RE.search(text)
    if f and f.group(1).strip():
        return "command", f.group(1).strip().splitlines()[0].strip()
    if flag_format:
        m = re.search(flag_format, text)
        if m:
            return "answer", m.group(0).strip()
    return "none", ""


def grade(task: Task, submitted: str) -> bool:
    if submitted is None:
        return False
    submitted = submitted.strip()
    if task.flag is not None:
        return submitted == task.flag.strip() or task.flag.strip() in submitted
    if task.flag_format is not None:
        return re.search(task.flag_format, submitted) is not None
    return False


class Agent:
    def __init__(self, llm: LLM, cfg: AgentConfig):
        self.llm = llm
        self.cfg = cfg

    def solve(self, task: Task, attempt: int = 0, logger=None) -> RunResult:
        """Public entry: guarantees the execution environment is torn down."""
        shell = build_shell(self.cfg, task.workdir)
        try:
            return self._solve(task, shell, attempt=attempt, logger=logger)
        finally:
            shell.close()

    def _solve(self, task: Task, shell, attempt: int = 0, logger=None) -> RunResult:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Task ({task.category}): {task.prompt}\n"
                                        f"Working directory contents are yours to explore."},
        ]
        steps: list[Step] = []
        memory = FindingsMemory()

        def _with_findings(content: str) -> str:
            fb = memory.block()
            return content + ("\n\n" + fb if fb else "")

        result = RunResult(
            task_id=task.task_id, attempt=attempt, solved=False,
            iterations=0, config=self.cfg.describe(),
        )

        consec_fail = 0
        for i in range(self.cfg.max_iterations):
            # Context management: the findings memory preserves key facts, so it is safe to
            # keep only the system prompt, the task, and the most recent turns — this stops a
            # small-context model from returning empty once the transcript grows large.
            if len(messages) > 12:
                messages[:] = messages[:2] + messages[-10:]
            try:
                raw = self.llm.chat(messages)
                consec_fail = 0
                reasoning = getattr(self.llm, "last_reasoning", "") or ""
            except Exception as e:
                consec_fail += 1
                if logger is not None:
                    logger.error(f"LLM call failed after retries: {e} (consecutive={consec_fail})")
                if consec_fail >= 3:
                    result.reason = f"llm error: {e}"
                    result.iterations = i
                    result.steps = steps
                    result.findings = memory.items
                    return result
                messages.append({"role": "user", "content": _with_findings(
                    "Your previous response was empty. Reply with a Thought and exactly one "
                    "`Command:` line.")})
                continue
            action_type, payload = parse_action(raw, task.flag_format)
            thought = raw.split("Command:")[0].split("Answer:")[0].strip()
            step = Step(index=i, thought=thought, reasoning=reasoning,
                        action_type=action_type, action=payload, raw_response=raw)
            messages.append({"role": "assistant", "content": raw})

            for note in NOTE_RE.findall(raw):
                if memory.add(note, "note") and logger is not None:
                    logger.info(f"finding+ [note]: {note.strip()}")

            def _emit_turn(tool_calls, action_kind):
                if logger is not None:
                    logger.add_turn(turn=i, message=payload if action_type == "answer" else raw,
                                    reason=thought, action_type=action_kind,
                                    tool_calls=tool_calls, reasoning=reasoning)

            if action_type == "answer":
                final, correction = ground_answer(payload, memory, task.flag_format)
                if correction and logger is not None:
                    logger.info(correction)
                step.observation = f"(submitted: {final})"
                _emit_turn(tool_calls=[], action_kind="output_text")
                steps.append(step)
                result.submitted_flag = final
                result.solved = grade(task, final)
                result.reason = "solved" if result.solved else "wrong flag submitted"
                result.iterations = i + 1
                result.steps = steps
                result.findings = memory.items
                return result

            if action_type == "command":
                obs = shell.run(payload)
                step.observation = obs
                _emit_turn(tool_calls=[{"tool": "bash", "input": payload, "output": obs}],
                           action_kind="tool_call")
                for frag in memory.capture_from_observation(obs, task.flag_format):
                    if logger is not None:
                        logger.info(f"finding+ [flag/auto]: {frag}")
                messages.append({"role": "user", "content": _with_findings(f"Observation:\n{obs}")})
            else:
                step.observation = "(no valid action parsed)"
                _emit_turn(tool_calls=[], action_kind="output_text")
                messages.append({"role": "user", "content": _with_findings(
                    "No action found. Respond with a single `Command:` or `Answer:` line.")})
            steps.append(step)

        result.iterations = self.cfg.max_iterations
        result.reason = "budget exhausted"
        result.steps = steps
        result.findings = memory.items
        return result
