"""Per-run working memory: a running list of facts the agent finds along the way.

Two kinds of entries:
  - note : model-curated ("Note: ..."), a reminder in the model's own words.
  - auto : harness-captured VERBATIM from command output (flag-format strings especially),
           so high-value strings are preserved byte-for-byte and never depend on the model
           retyping them correctly.

The memory is re-injected into the prompt every turn as a compact reference, and is used at
submit time to correct a mistyped answer against a verbatim-captured flag.
"""
from __future__ import annotations

import difflib
import re
import time
from dataclasses import dataclass, field


@dataclass
class FindingsMemory:
    items: list[dict] = field(default_factory=list)  # {source, text, timestamp}

    def add(self, text: str, source: str) -> bool:
        text = text.strip()
        if not text:
            return False
        if any(it["text"] == text for it in self.items):
            return False
        self.items.append({"source": source, "text": text,
                           "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")})
        return True

    def capture_from_observation(self, obs: str, flag_regex: str | None) -> list[str]:
        """Auto-capture verbatim flag-format matches from a command's output."""
        added = []
        if flag_regex:
            for m in re.findall(flag_regex, obs):
                frag = m if isinstance(m, str) else m[0]
                # Skip format placeholders like HTB{*****...} (real flags never contain '*').
                if "*" in frag:
                    continue
                if self.add(frag, "auto"):
                    added.append(frag)
        return added

    def flag_candidates(self, flag_regex: str | None) -> list[str]:
        """Verbatim flag-format strings the memory has captured/seen."""
        if not flag_regex:
            return []
        out = []
        for it in self.items:
            for m in re.findall(flag_regex, it["text"]):
                out.append(m if isinstance(m, str) else m[0])
        return out

    def block(self) -> str:
        """Compact reference injected into the prompt each turn."""
        if not self.items:
            return ""
        lines = ["Findings so far (verbatim; copy any flag EXACTLY from here):"]
        for it in self.items:
            tag = "flag/auto" if it["source"] == "auto" else "note"
            lines.append(f"  - [{tag}] {it['text']}")
        return "\n".join(lines)


def ground_answer(submitted: str, memory: FindingsMemory, flag_regex: str | None,
                  threshold: float = 0.9) -> tuple[str, str | None]:
    """If the submitted flag is a near-miss of a verbatim-captured flag, prefer the captured
    one. Returns (final_answer, correction_note_or_None). Only ever swaps to a string the agent
    actually observed in its own command output — never invents one."""
    if not flag_regex:
        return submitted, None
    m = re.search(flag_regex, submitted)
    sub_flag = m.group(0) if m else submitted.strip()
    best, best_ratio = None, 0.0
    for cand in memory.flag_candidates(flag_regex):
        if cand == sub_flag:
            return submitted, None  # already grounded — exact match to an observed flag
        r = difflib.SequenceMatcher(None, sub_flag, cand).ratio()
        if r > best_ratio:
            best, best_ratio = cand, r
    if best is not None and best_ratio >= threshold and best != sub_flag:
        note = (f"grounded answer: submitted {sub_flag!r} corrected to verbatim observed "
                f"{best!r} (similarity {best_ratio:.2f})")
        return best, note
    return submitted, None
