#!/usr/bin/env python3
"""Preflight check -- run this FIRST, before any real task run.

Verifies the environment is actually ready: model server reachable, decoding budget
sane, Docker daemon up, shared_net exists, the cybench execution image present. Each
check is fast (a few seconds) and fails loudly with the exact fix, rather than letting
a 20-minute run die halfway through on something checkable in advance.

Usage:
    ./.venv/bin/python scripts/preflight.py
Exit code 0 = everything checked out. Non-zero = read the [FAIL] lines.
"""
from __future__ import annotations

import subprocess
import sys
import time

sys.path.insert(0, ".")
from agent.config import AgentConfig  # noqa: E402

PASS, FAIL, WARN = "[PASS]", "[FAIL]", "[WARN]"
failures: list[str] = []


def check(label: str, fn):
    try:
        detail = fn()
        print(f"{PASS} {label}" + (f" -- {detail}" if detail else ""))
    except Exception as e:
        print(f"{FAIL} {label} -- {e}")
        failures.append(label)


def warn(label: str, msg: str):
    print(f"{WARN} {label} -- {msg}")


def check_config():
    cfg = AgentConfig()
    if cfg.max_tokens < 2048:
        raise RuntimeError(
            f"AGENT_MAX_TOKENS={cfg.max_tokens} is too low for a reasoning model -- it will "
            f"silently return empty completions. Set AGENT_MAX_TOKENS>=2048 (4096 recommended) "
            f"in .env."
        )
    return f"model={cfg.model} max_tokens={cfg.max_tokens} shell={cfg.shell_backend}"


def check_model_server():
    cfg = AgentConfig()
    from openai import OpenAI
    client = OpenAI(api_key=cfg.api_key, base_url=cfg.base_url)
    t0 = time.time()
    resp = client.chat.completions.create(
        model=cfg.model,
        messages=[{"role": "user", "content": "Reply with exactly: OK"}],
        max_tokens=cfg.max_tokens, temperature=0, stream=False,
    )
    text = (resp.choices[0].message.content or "").strip()
    dt = time.time() - t0
    if not text:
        raise RuntimeError(
            "server returned an EMPTY completion. If this is a reasoning model (hidden "
            "reasoning tokens eat the budget before visible output), raise AGENT_MAX_TOKENS. "
            "If using LM Studio, also check Speculative Decoding is OFF -- it causes "
            "intermittent empty/garbled responses."
        )
    return f"replied {text!r} in {dt:.1f}s"


def check_docker_daemon():
    cfg = AgentConfig()
    import os
    env = os.environ.copy()
    if cfg.docker_config:
        env["DOCKER_CONFIG"] = cfg.docker_config
    p = subprocess.run(["docker", "version", "--format", "{{.Server.Version}}"],
                       capture_output=True, text=True, env=env, timeout=15)
    if p.returncode != 0:
        raise RuntimeError(f"docker not reachable: {p.stderr.strip()[:200]}")
    return f"server {p.stdout.strip()}"


def check_network():
    cfg = AgentConfig()
    p = subprocess.run(["docker", "network", "ls", "--format", "{{.Name}}"],
                       capture_output=True, text=True, timeout=15)
    nets = p.stdout.split()
    net = cfg.docker_network
    if net not in nets:
        raise RuntimeError(
            f"docker network '{net}' does not exist. Fix: docker network create {net}"
        )
    return f"'{net}' exists"


def check_image():
    cfg = AgentConfig()
    if cfg.shell_backend != "docker":
        return "skipped (AGENT_SHELL=local)"
    p = subprocess.run(["docker", "image", "inspect", cfg.docker_image],
                       capture_output=True, text=True, timeout=15)
    if p.returncode != 0:
        raise RuntimeError(
            f"image '{cfg.docker_image}' not present locally. Fix: "
            f"docker pull {cfg.docker_image}  (~55GB, only needed once)"
        )
    return f"'{cfg.docker_image}' present"


def check_memory_headroom():
    with open("/proc/meminfo") as f:
        info = dict(line.split(":", 1) for line in f if ":" in line)
    avail_kb = int(info["MemAvailable"].strip().split()[0])
    avail_gb = avail_kb / 1024 / 1024
    if avail_gb < 1.5:
        warn("memory headroom", f"only {avail_gb:.1f}GB available -- a long run may be killed "
             f"by low free memory even if 'available' looks OK; consider closing other apps.")
    else:
        print(f"{PASS} memory headroom -- {avail_gb:.1f}GB available")


def main() -> int:
    print("=== Security Agent Harness -- Preflight ===\n")
    check("config (pinned model + budget)", check_config)
    check("model server reachable & responds", check_model_server)
    check("docker daemon reachable", check_docker_daemon)
    check("docker network exists", check_network)
    check("cybench execution image present", check_image)
    check_memory_headroom()

    print()
    if failures:
        print(f"RESULT: {len(failures)} check(s) FAILED -- fix these before running a task:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("RESULT: all checks passed. Safe to run a task, e.g.:")
    print("  ./.venv/bin/python run.py --task <path to task.json> --k 3")
    return 0


if __name__ == "__main__":
    sys.exit(main())
