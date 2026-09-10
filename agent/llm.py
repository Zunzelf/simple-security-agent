"""LLM client abstraction.

`OpenAILLM` talks to any OpenAI-compatible chat endpoint. `MockLLM` is a scripted,
observation-reactive stand-in so the harness runs end-to-end with no API key — useful
for CI, demos, and validating the loop itself.
"""
from __future__ import annotations

import re
from typing import Protocol

from .config import AgentConfig


class LLM(Protocol):
    def chat(self, messages: list[dict]) -> str: ...


class OpenAILLM:
    def __init__(self, cfg: AgentConfig):
        from openai import OpenAI
        self.cfg = cfg
        self.client = OpenAI(api_key=cfg.api_key, base_url=cfg.base_url)
        self.last_reasoning = ""

    def chat(self, messages: list[dict]) -> str:
        """Call chat.completions with retry+backoff. A slow/self-hosted model may drop the
        stream mid-generation (APIError: terminated) or time out; one transient failure must
        not abort a whole run, so we retry a few times before giving up."""
        import time
        last_err = None
        for attempt in range(max(1, self.cfg.max_retries)):
            try:
                return self._chat_once(messages)
            except Exception as e:  # transient server/stream/connection issues
                last_err = e
                if attempt + 1 < self.cfg.max_retries:
                    time.sleep(min(2 ** attempt, 8))
        raise last_err

    def _chat_once(self, messages: list[dict]) -> str:
        params = dict(
            model=self.cfg.model,
            messages=messages,
            temperature=self.cfg.temperature,
            top_p=self.cfg.top_p,
            max_tokens=self.cfg.max_tokens,
            seed=self.cfg.seed,
        )
        if not self.cfg.stream:
            msg = self.client.chat.completions.create(**params).choices[0].message
            text = msg.content or ""
            self.last_reasoning = getattr(msg, "reasoning_content", None) or getattr(msg, "reasoning", "") or ""
            if not text.strip():
                raise ValueError("empty completion")
            return text

        chunks: list[str] = []
        rchunks: list[str] = []
        stream = self.client.chat.completions.create(**params, stream=True)
        for event in stream:
            if not event.choices:
                continue
            delta = event.choices[0].delta
            piece = getattr(delta, "content", None)
            if piece:
                chunks.append(piece)
            rpiece = getattr(delta, "reasoning_content", None) or getattr(delta, "reasoning", None)
            if rpiece:
                rchunks.append(rpiece)
        text = "".join(chunks)
        self.last_reasoning = "".join(rchunks)
        if not text.strip():
            # ornith's server occasionally returns an empty stream; retrying beats
            # burning a whole agent iteration on a no-op turn.
            raise ValueError("empty completion")
        return text


class MockLLM:
    """A tiny reactive agent: explores, reads promising files, then submits a flag it
    has seen. Enough to exercise the whole loop deterministically."""

    FLAG_RE = re.compile(r"(flag\{[^}]*\}|HTB\{[^}]*\}|[A-Za-z0-9_]+CTF\{[^}]*\})")

    def chat(self, messages: list[dict]) -> str:
        # Only trust flags seen in actual command OUTPUT (observation messages),
        # never the task prompt (which may show the flag *format* as an example).
        observations = "\n".join(
            m["content"] for m in messages
            if m["role"] == "user" and m["content"].startswith("Observation:")
        )
        history = "\n".join(m["content"] for m in messages)

        # 1) If a flag has appeared in observed output, submit it.
        m = self.FLAG_RE.search(observations)
        if m:
            return f"I found the flag in the file contents.\nAnswer: {m.group(1)}"

        # 2) Read the next file we have seen but not yet inspected.
        seen_files = re.findall(r"([\w./-]+\.(?:txt|md|py|c|log|conf|json))", observations)
        already_read = set(re.findall(r"cat\s+([\w./-]+)", history))
        for fname in dict.fromkeys(seen_files):        # preserve order, dedupe
            if fname not in already_read:
                return f"That file may hold the flag.\nCommand: cat {fname}"

        # 3) Otherwise, look around.
        return "Let me enumerate the working directory first.\nCommand: ls -la"


def build_llm(cfg: AgentConfig) -> LLM:
    if cfg.use_mock_llm or not cfg.api_key:
        return MockLLM()
    return OpenAILLM(cfg)
