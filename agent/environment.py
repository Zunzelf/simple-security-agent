"""Execution environments for the agent's shell.

`LocalShell` runs commands on the host. `DockerShell` runs them inside the benchmark's own
container image (Kali + upx/radare2/gdb/...), which is what the reference agent gets — using
it keeps the comparison about agent quality rather than about who had which tools installed.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

MAX_OUTPUT_CHARS = 6000  # keep observations from blowing up the context window
CONTAINER_WORKDIR = "/tmp/cyber-bench"  # same path cybench gives its agent


def _format(out: str, err: str, code: int) -> str:
    body = out or ""
    if err.strip():
        body += ("\n[stderr]\n" + err)
    body = body.strip() or "(no output)"
    body += f"\n[exit code: {code}]"
    if len(body) > MAX_OUTPUT_CHARS:
        body = body[:MAX_OUTPUT_CHARS] + "\n[...output truncated...]"
    return body


class LocalShell:
    def __init__(self, workdir: str, timeout: int = 60):
        self.workdir = workdir
        self.timeout = timeout

    def run(self, command: str) -> str:
        try:
            p = subprocess.run(command, shell=True, cwd=self.workdir, executable="/bin/bash",
                               capture_output=True, text=True, timeout=self.timeout)
            return _format(p.stdout, p.stderr, p.returncode)
        except subprocess.TimeoutExpired:
            return f"[command timed out after {self.timeout}s]"
        except Exception as e:
            return f"[execution error: {e}]"

    def close(self) -> None:
        pass


class DockerShell:
    """A persistent container; each command runs via `docker exec` (stateless per command,
    but the filesystem and anything installed persist across the run, like a real shell)."""

    def __init__(self, image: str, workdir: str, timeout: int = 60,
                 network: str | None = None, docker_config: str | None = None):
        self.timeout = timeout
        self.workdir = str(Path(workdir).resolve())
        self.env = os.environ.copy()
        if docker_config:
            self.env["DOCKER_CONFIG"] = docker_config

        # A killed run (e.g. OOM) can leave the container behind, so sweep stale ones first.
        subprocess.run("docker ps -q -f label=secagent=1 | xargs -r docker rm -f",
                       shell=True, capture_output=True, text=True, env=self.env)

        args = ["docker", "run", "-d", "--rm", "--label", "secagent=1",
                "-v", f"{self.workdir}:{CONTAINER_WORKDIR}",
                "-w", CONTAINER_WORKDIR,
                # match host uid so files the agent creates stay deletable by us
                "--user", f"{os.getuid()}:{os.getgid()}"]
        if network:
            args += ["--network", network]
        args += ["--entrypoint", "/bin/bash", image, "-c", "sleep infinity"]
        p = subprocess.run(args, capture_output=True, text=True, env=self.env)
        if p.returncode != 0:
            raise RuntimeError(f"could not start container: {p.stderr.strip()[:300]}")
        self.cid = p.stdout.strip()

    def run(self, command: str) -> str:
        try:
            p = subprocess.run(["docker", "exec", "-i", self.cid, "bash", "-c", command],
                               capture_output=True, text=True, timeout=self.timeout,
                               env=self.env)
            return _format(p.stdout, p.stderr, p.returncode)
        except subprocess.TimeoutExpired:
            return f"[command timed out after {self.timeout}s]"
        except Exception as e:
            return f"[execution error: {e}]"

    def close(self) -> None:
        subprocess.run(["docker", "rm", "-f", self.cid],
                       capture_output=True, text=True, env=self.env)


def build_shell(cfg, workdir: str):
    if getattr(cfg, "shell_backend", "local") == "docker":
        return DockerShell(cfg.docker_image, workdir, timeout=cfg.command_timeout,
                           network=cfg.docker_network, docker_config=cfg.docker_config)
    return LocalShell(workdir, timeout=cfg.command_timeout)


# Backwards-compatible alias
Shell = LocalShell
