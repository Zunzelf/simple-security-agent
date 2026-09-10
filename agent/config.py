"""Harness configuration.

Everything that affects reproducibility (model, decoding params, budget) is pinned
here and overridable via environment / .env. Keeping it in one Pydantic model means a
run can be fully described (and logged) by a single object.
"""
from __future__ import annotations

import os
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()


class AgentConfig(BaseModel):
    # --- Model / API (OpenAI-compatible; hosted or self-hosted) ---
    model: str = Field(default_factory=lambda: os.getenv("AGENT_MODEL", "gpt-4o-mini"))
    base_url: str | None = Field(default_factory=lambda: os.getenv("OPENAI_BASE_URL") or None)
    api_key: str | None = Field(default_factory=lambda: os.getenv("OPENAI_API_KEY") or None)

    # --- Decoding params (pinned for reproducibility) ---
    temperature: float = Field(default_factory=lambda: float(os.getenv("AGENT_TEMPERATURE", "0.5")))
    top_p: float = Field(default_factory=lambda: float(os.getenv("AGENT_TOP_P", "1.0")))
    max_tokens: int = Field(default_factory=lambda: int(os.getenv("AGENT_MAX_TOKENS", "4096")))
    seed: int = Field(default_factory=lambda: int(os.getenv("AGENT_SEED", "0")))

    # --- Agent loop budget ---
    max_iterations: int = Field(default_factory=lambda: int(os.getenv("AGENT_MAX_ITERS", "15")))
    command_timeout: int = Field(default_factory=lambda: int(os.getenv("AGENT_CMD_TIMEOUT", "60")))

    # --- Harness options ---
    use_mock_llm: bool = Field(default_factory=lambda: os.getenv("AGENT_MOCK", "0") == "1")
    stream: bool = Field(default_factory=lambda: os.getenv("AGENT_STREAM", "1") == "1")
    max_retries: int = Field(default_factory=lambda: int(os.getenv("AGENT_MAX_RETRIES", "4")))

    # --- Execution backend: "local" (host shell) or "docker" (benchmark container) ---
    shell_backend: str = Field(default_factory=lambda: os.getenv("AGENT_SHELL", "local"))
    docker_image: str = Field(default_factory=lambda: os.getenv("AGENT_DOCKER_IMAGE", "cybench/cybench:latest"))
    docker_network: str = Field(default_factory=lambda: os.getenv("AGENT_DOCKER_NETWORK", "shared_net"))
    docker_config: str | None = Field(default_factory=lambda: os.getenv("DOCKER_CONFIG") or None)

    def describe(self) -> dict:
        """Reproducibility fingerprint (no secrets)."""
        d = self.model_dump()
        d.pop("api_key", None)
        return d
