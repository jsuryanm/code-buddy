"""HTTP/SSE client for the CodeBuddy API. No Streamlit imports, so it is easy to unit test."""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator

import httpx


def parse_sse(lines: Iterable[str]) -> Iterator[tuple[str, dict]]:
    """Parse Server-Sent Events into (event, data) pairs."""
    event = "message"
    data: list[str] = []
    for raw in lines:
        line = raw.rstrip("\r\n")
        if line == "":
            if data:
                yield event, json.loads("\n".join(data))
            event, data = "message", []
        elif line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].lstrip())
    if data:
        yield event, json.loads("\n".join(data))


class ApiError(Exception):
    """A failed API call. `status` is the HTTP status, or None when there was no HTTP status.

    `reached` is False only when the request never got to the server (it could not connect).
    A stream that breaks after a 200 has no status but did reach it. Defaults to `status`
    being set.
    """

    def __init__(self, message: str, status: int | None = None, reached: bool | None = None):
        super().__init__(message)
        self.status = status
        self.reached = status is not None if reached is None else reached


class TutorClient:
    def __init__(
        self,
        base_url: str,
        timeout: float = 90.0,
        transport: httpx.BaseTransport | None = None,
        api_key: str | None = None,
    ):
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._http = httpx.Client(
            base_url=base_url, timeout=timeout, transport=transport, headers=headers
        )

    def _stream(self, path: str, payload: dict) -> Iterator[tuple[str, dict]]:
        try:
            with self._http.stream("POST", path, json=payload) as resp:
                if resp.status_code != 200:
                    resp.read()
                    raise ApiError(
                        f"API returned {resp.status_code}: {resp.text[:200]}", resp.status_code
                    )
                yield from parse_sse(resp.iter_lines())
        except httpx.HTTPError as exc:
            reached = not isinstance(exc, httpx.ConnectError | httpx.ConnectTimeout)
            raise ApiError(
                f"Cannot reach the API at {self._http.base_url}: {exc}", reached=reached
            ) from exc

    def stream_turn(
        self,
        session_id: str,
        message: str,
        code: str | None,
        language: str = "python",
        learner_id: str | None = None,
    ) -> Iterator[tuple[str, dict]]:
        payload = {"session_id": session_id, "message": message, "code": code, "language": language}
        if learner_id:
            payload["learner_id"] = learner_id
        return self._stream("/v1/turn", payload)

    def stream_show_answer(
        self,
        session_id: str,
        code: str | None,
        language: str = "python",
        learner_id: str | None = None,
    ) -> Iterator[tuple[str, dict]]:
        payload = {"session_id": session_id, "code": code, "language": language}
        if learner_id:
            payload["learner_id"] = learner_id
        return self._stream("/v1/show-answer", payload)

    def stream_quiz(
        self, session_id: str, learner_id: str | None = None
    ) -> Iterator[tuple[str, dict]]:
        payload = {"session_id": session_id}
        if learner_id:
            payload["learner_id"] = learner_id
        return self._stream("/v1/quiz", payload)

    def _memory_call(self, method: str, path: str, learner_token: str | None = None) -> dict:
        headers = {"X-Learner-Token": learner_token} if learner_token else {}
        try:
            resp = self._http.request(method, f"/v1/memory{path}", headers=headers)
        except httpx.HTTPError as exc:
            raise ApiError(f"Cannot reach the API at {self._http.base_url}: {exc}") from exc
        if resp.status_code != 200:
            detail = (
                resp.json().get("detail")
                if resp.headers.get("content-type", "").startswith("application/json")
                else resp.text[:200]
            )
            raise ApiError(
                f"Memory request failed ({resp.status_code}): {detail}", resp.status_code
            )
        return resp.json()

    def new_learner(self) -> str:
        """Ask the server for a signed learner token (ids are never made client-side)."""
        return self._memory_call("POST", "/learners")["learner_token"]

    def memories(self, learner_token: str) -> list[dict]:
        return self._memory_call("GET", "", learner_token)["items"]

    def forget(self, learner_token: str) -> int:
        return self._memory_call("DELETE", "", learner_token)["deleted"]

    def stream_approve(
        self, session_id: str, turn_id: str, approve: bool, remember: bool = True
    ) -> Iterator[tuple[str, dict]]:
        payload = {
            "session_id": session_id,
            "turn_id": turn_id,
            "approve": approve,
            "remember": remember,
        }
        return self._stream("/v1/approve", payload)

    def transcribe(
        self, audio: bytes, filename: str = "speech.wav", content_type: str = "audio/wav"
    ) -> str:
        """Send recorded audio to the API and return the transcript text."""
        try:
            resp = self._http.post("/v1/stt", files={"audio": (filename, audio, content_type)})
        except httpx.HTTPError as exc:
            raise ApiError(f"Cannot reach the API at {self._http.base_url}: {exc}") from exc
        if resp.status_code != 200:
            detail = (
                resp.json().get("detail")
                if resp.headers.get("content-type", "").startswith("application/json")
                else resp.text[:200]
            )
            raise ApiError(f"Voice input failed ({resp.status_code}): {detail}", resp.status_code)
        return resp.json()["text"]

    def health(self) -> dict | None:
        try:
            return self._http.get("/healthz", timeout=3).json()
        except (httpx.HTTPError, ValueError):
            return None
