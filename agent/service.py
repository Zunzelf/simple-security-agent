"""Challenge-service lifecycle for docker-compose based cybench tasks.

Mirrors what cybench's own run_task.py does around its agent: bring the task's service up
on the shared docker network, verify it is actually reachable from a container on that
network (the address is container-DNS, e.g. "web:8080" -- not localhost, since the agent
itself runs in a container on the same network), then tear the service down when the run
finishes, always, even on crash.
"""
from __future__ import annotations

import os
import subprocess
import time

from .models import Task

DEFAULT_NETWORK = "shared_net"


class ServiceError(RuntimeError):
    """The task's challenge service could not be started or never became reachable."""


class ChallengeService:
    def __init__(self, task: Task, probe_image: str, docker_config: str | None = None):
        self.task = task
        self.env = task.env
        self.probe_image = probe_image
        self.docker_env = os.environ.copy()
        if docker_config:
            self.docker_env["DOCKER_CONFIG"] = docker_config
        # A stable, task-scoped compose project name -- keeps `docker compose ls` readable
        # and stops every task's containers (all named "env" by directory default) colliding.
        self.project = f"secagent-{task.task_id}"
        self._up = False

    @property
    def is_up(self) -> bool:
        return self._up

    def start(self, health_timeout: int = 90) -> None:
        if self.env.type != "docker-compose":
            return
        if not self.env.compose_file:
            raise ServiceError(f"{self.task.task_id}: env.type=docker-compose but no compose_file set")

        # A killed run (e.g. OOM) skips our `finally`/stop(), which can leave THIS task's
        # stack running. Sweep it first so `up` always starts from a clean slate.
        subprocess.run(
            ["docker", "compose", "-p", self.project, "-f", self.env.compose_file, "down", "-v"],
            capture_output=True, text=True, env=self.docker_env,
        )

        p = subprocess.run(
            ["docker", "compose", "-p", self.project, "-f", self.env.compose_file,
             "up", "--build", "-d"],
            capture_output=True, text=True, env=self.docker_env,
        )
        if p.returncode != 0:
            raise ServiceError(f"{self.task.task_id}: compose up failed: {p.stderr.strip()[-500:]}")
        self._up = True

        if self.env.target_host:
            self._wait_healthy(self.env.target_host, timeout=health_timeout)

    def _wait_healthy(self, target_host: str, timeout: int) -> None:
        host, _, port = target_host.partition(":")
        port = port or "80"
        network = self.env.network or DEFAULT_NETWORK
        # --entrypoint is required: cybench/cybench:latest's own ENTRYPOINT would otherwise
        # swallow our command instead of running it.
        probe = ["docker", "run", "--rm", "--network", network, "--entrypoint", "bash",
                 self.probe_image, "-c",
                 f'python3 -c "import socket; s=socket.socket(); s.settimeout(3); '
                 f's.connect((\'{host}\', {port}))" 2>&1']
        deadline = time.time() + timeout
        last_err = ""
        while time.time() < deadline:
            p = subprocess.run(probe, capture_output=True, text=True, env=self.docker_env)
            if p.returncode == 0:
                return
            last_err = (p.stdout + p.stderr).strip()[-200:]
            time.sleep(2)
        raise ServiceError(
            f"{self.task.task_id}: {target_host} did not become reachable within "
            f"{timeout}s on network '{network}' (last error: {last_err})"
        )

    def stop(self) -> None:
        if not self._up:
            return
        subprocess.run(
            ["docker", "compose", "-p", self.project, "-f", self.env.compose_file,
             "down", "-v"],
            capture_output=True, text=True, env=self.docker_env,
        )
        self._up = False
