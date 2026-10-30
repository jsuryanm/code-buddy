import httpx
import pytest

from codebuddy.ui.client import ApiError, TutorClient, parse_sse


def test_parse_sse_events():
    lines = [
        "event: meta",
        'data: {"mode": "hint"}',
        "",
        "event: token",
        'data: {"text": "hi"}',
        "",
        "event: done",
        'data: {"ttft_ms": 5}',
        "",
    ]
    assert list(parse_sse(lines)) == [
        ("meta", {"mode": "hint"}),
        ("token", {"text": "hi"}),
        ("done", {"ttft_ms": 5}),
    ]


def test_parse_sse_handles_missing_trailing_blank_line():
    assert list(parse_sse(["event: token", 'data: {"text": "x"}'])) == [("token", {"text": "x"})]


def _client(handler) -> TutorClient:
    return TutorClient("http://api", transport=httpx.MockTransport(handler))


def test_stream_turn_sends_payload_and_parses_response():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.read().decode()
        body = 'event: token\ndata: {"text": "ok"}\n\n'
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    events = list(_client(handler).stream_turn("s", "hello", "x = 1"))
    assert events == [("token", {"text": "ok"})]
    assert '"session_id":"s"' in seen["body"].replace(" ", "") and "x = 1" in seen["body"]


def test_http_error_becomes_api_error():
    client = _client(lambda r: httpx.Response(500, text="boom"))
    with pytest.raises(ApiError):
        list(client.stream_turn("s", "hello", None))


def test_unreachable_api_is_an_api_error_and_health_is_none():
    def handler(request):
        raise httpx.ConnectError("refused")

    client = _client(handler)
    assert client.health() is None
    with pytest.raises(ApiError):
        list(client.stream_show_answer("s", None))


def test_api_key_is_sent_as_bearer_token():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"status": "ok"})

    client = TutorClient("http://api", transport=httpx.MockTransport(handler), api_key="k1")
    assert client.health() == {"status": "ok"} and seen["auth"] == "Bearer k1"


def test_transcribe_uploads_audio_and_returns_text():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["type"] = request.headers["content-type"]
        seen["body"] = request.read()
        return httpx.Response(200, json={"text": "hello", "provider": "groq"})

    client = TutorClient("http://api", transport=httpx.MockTransport(handler))
    assert client.transcribe(b"RIFFdata", "a.wav", "audio/wav") == "hello"
    assert seen["type"].startswith("multipart/form-data") and b"RIFFdata" in seen["body"]


def test_transcribe_failure_has_a_readable_message():
    client = TutorClient(
        "http://api",
        transport=httpx.MockTransport(lambda r: httpx.Response(503, json={"detail": "not set up"})),
    )
    with pytest.raises(ApiError, match="not set up"):
        client.transcribe(b"x")


def test_stream_approve_posts_the_decision():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.read().decode()
        return httpx.Response(200, text='event: done\ndata: {"ok": true}\n\n')

    client = TutorClient("http://api", transport=httpx.MockTransport(handler))
    assert list(client.stream_approve("s", "t", False, remember=False)) == [("done", {"ok": True})]
    assert '"approve":false' in seen["body"].replace(" ", "") and '"turn_id":"t"' in seen["body"]
