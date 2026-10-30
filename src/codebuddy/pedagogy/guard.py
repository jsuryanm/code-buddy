"""Streaming answer-leak guard (spec 8.5).

Blocks corrected code at hint levels 0-3. It is a rule check that works on the token
stream so it adds almost no latency: prose is released as soon as its first word is
known not to start a code line, and suspect lines are held until the line ends.
The LLM judge from the spec runs in evals and sampled monitoring, not here.
"""

from __future__ import annotations

import re

_PSEUDO_FENCE_LANGS = {"", "text", "txt", "plaintext", "pseudo", "pseudocode"}
_KEYWORDS = {
    "for", "while", "if", "elif", "else", "def", "class", "return", "import", "from",
    "try", "except", "finally", "with",
}  # fmt: skip

_BLOCK_LINE = re.compile(
    r"^\s*(for|while|if|elif|else|def|class|try|except|finally|with)\b[^\n]*[:)]\s*$"
)
_SIMPLE_STMT = re.compile(r"^\s*(return\s+\S|import\s+\w|from\s+\w+\s+import\s)")
_ASSIGN = re.compile(r"^\s*[A-Za-z_][\w.\[\]]*\s*(?:[+\-*/%]|//)?=(?!=)\s*\S")
_FIRST_TOKEN = re.compile(r"([A-Za-z_][\w.\[\]]*)(.?)")
_ASSIGN_AHEAD = re.compile(r"\s*(?:[+\-*/%]|//)?=(?!=)")


class LeakDetected(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class StreamGuard:
    """Feed streamed text, get back the text that is safe to show now.

    enforce=False turns the guard off (concept explanations, reveals).
    allow_pseudocode=True permits fenced pseudo-code (hint level 3).
    """

    def __init__(self, enforce: bool = True, allow_pseudocode: bool = False):
        self.enforce = enforce
        self.allow_pseudocode = allow_pseudocode
        self._buf = ""  # current, unfinished line
        self._emitted = 0  # chars of the current line already released
        self._in_fence = False
        self._fence_ok = False

    def feed(self, chunk: str) -> str:
        if not self.enforce:
            return chunk
        out: list[str] = []
        self._buf += chunk
        while (nl := self._buf.find("\n")) != -1:
            line, self._buf = self._buf[: nl + 1], self._buf[nl + 1 :]
            out.append(self._finish_line(line))
        out.append(self._release_partial())
        return "".join(out)

    def flush(self) -> str:
        if not self.enforce or not self._buf:
            return ""
        line, self._buf = self._buf, ""
        return self._finish_line(line)

    # -- internals -----------------------------------------------------------------

    def _finish_line(self, line: str) -> str:
        self._check_line(line)
        released, self._emitted = line[self._emitted :], 0
        return released

    def _check_line(self, line: str) -> None:
        stripped = line.strip()
        if stripped.startswith("```"):
            if self._in_fence:
                self._in_fence = False
                return
            lang = stripped[3:].strip().lower()
            self._fence_ok = self.allow_pseudocode and lang in _PSEUDO_FENCE_LANGS
            if not self._fence_ok:
                raise LeakDetected("fenced code block")
            self._in_fence = True
            return
        if self._in_fence:
            return
        if _BLOCK_LINE.match(line) or _SIMPLE_STMT.match(line) or _ASSIGN.match(line):
            raise LeakDetected(f"code statement: {stripped[:60]}")

    def _release_partial(self) -> str:
        if self._in_fence or not self._buf[self._emitted :]:
            return ""
        if self._prefix_is_safe(self._buf):
            released = self._buf[self._emitted :]
            self._emitted = len(self._buf)
            return released
        return ""

    @staticmethod
    def _prefix_is_safe(partial: str) -> bool:
        """True when the unfinished line cannot turn into a code line."""
        s = partial.lstrip()
        if not s:
            return False
        if s.startswith("`"):
            if set(s) == {"`"} and len(s) < 3:
                return False  # could still become ```
            return not s.startswith("```")
        m = _FIRST_TOKEN.match(s)
        if m is None:
            return True  # starts with a digit or punctuation
        token, following = m.groups()
        if not following:
            return False  # token may continue
        rest = s[len(token) :]
        if token in _KEYWORDS and following in " (:":
            return False  # hold until the line ends, then judge the whole line
        if not rest.strip():
            return False  # cannot see past the whitespace yet
        return not _ASSIGN_AHEAD.match(rest)
