"""Pydantic schemas shared across the harness."""
from __future__ import annotations

from typing import Literal, Optional
from pydantic import BaseModel, Field


class TaskEnv(BaseModel):
    """A challenge service the task needs running before the agent starts.

    `target_host` is a container-DNS address (e.g. "web:8080") on `network`, NOT localhost --
    the agent runs inside its own container on that same network, so it reaches the challenge
    the same way cybench's own reference agent does.
    """
    type: Literal["none", "docker-compose"] = "none"
    compose_file: Optional[str] = None   # resolved to an absolute path by the loader
    start_script: Optional[str] = None
    stop_script: Optional[str] = None
    target_host: Optional[str] = None
    network: Optional[str] = None


class Task(BaseModel):
    """A single security task (CTF challenge or vuln PoC)."""
    task_id: str
    benchmark: Literal["cybench", "cybergym", "demo"] = "demo"
    category: str = "misc"
    prompt: str                      # what the agent is asked to do
    workdir: str                     # directory the agent operates in
    flag: Optional[str] = None       # ground-truth flag for grading (if known)
    flag_format: Optional[str] = None  # regex the flag should match, e.g. r"flag\{.*\}"
    env: TaskEnv = Field(default_factory=TaskEnv)
    metadata: dict = Field(default_factory=dict)


class Step(BaseModel):
    """One iteration of the agent loop."""
    index: int
    thought: str = ""                # parsed "Thought:" line
    reasoning: str = ""              # full model chain-of-thought (reasoning trace)
    action_type: Literal["command", "answer", "none"] = "none"
    action: str = ""                 # command text or submitted flag
    observation: str = ""            # execution output
    raw_response: str = ""           # full model output (for the trace)


class RunResult(BaseModel):
    """Outcome of a single attempt at a task."""
    task_id: str
    attempt: int
    solved: bool
    submitted_flag: Optional[str] = None
    iterations: int
    reason: str = ""                 # why it ended (solved / budget / error)
    config: dict = Field(default_factory=dict)
    steps: list[Step] = Field(default_factory=list)
    findings: list[dict] = Field(default_factory=list)
