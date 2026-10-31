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


def _capture(seen):
    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = request.read().decode().replace(" ", "")
        return httpx.Response(200, text='event: done\ndata: {"ok": true}\n\n')

    return TutorClient("http://api", transport=httpx.MockTransport(handler))


def test_learner_id_is_sent_only_when_set():
    seen = {}
    client = _capture(seen)
    list(client.stream_turn("s", "hi", None))
    list(client.stream_show_answer("s", None))
    assert "learner_id" not in seen["body"]
    list(client.stream_turn("s", "hi", None, learner_id="a" * 16))
    assert f'"learner_id":"{"a" * 16}"' in seen["body"]
    list(client.stream_show_answer("s", None, learner_id="b" * 16))
    assert f'"learner_id":"{"b" * 16}"' in seen["body"]


def test_memories_and_forget_call_the_memory_routes():
    seen = []
    token = "a" * 22 + "." + "b" * 43

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, request.headers.get("x-learner-token")))
        if request.method == "POST":
            return httpx.Response(200, json={"learner_token": token})
        if request.method == "GET":
            return httpx.Response(200, json={"items": [{"kind": "semantic", "text": "x"}]})
        return httpx.Response(200, json={"deleted": 3})

    client = TutorClient("http://api", transport=httpx.MockTransport(handler))
    assert client.new_learner() == token
    assert client.memories(token) == [{"kind": "semantic", "text": "x"}]
    assert client.forget(token) == 3
    assert seen == [
        ("POST", "/v1/memory/learners", None),
        ("GET", "/v1/memory", token),  # the token never appears in a path (access logs)
        ("DELETE", "/v1/memory", token),
    ]


def test_memory_failures_have_readable_messages():
    client = TutorClient(
        "http://api",
        transport=httpx.MockTransport(lambda r: httpx.Response(503, json={"detail": "disabled"})),
    )
    with pytest.raises(ApiError, match="disabled"):
        client.memories("a" * 16)
    with pytest.raises(ApiError, match="disabled"):
        client.forget("a" * 16)
    with pytest.raises(ApiError, match="disabled"):
        client.new_learner()


def test_api_error_carries_the_status_and_none_when_unreachable():
    with pytest.raises(ApiError) as err:
        list(
            _client(lambda r: httpx.Response(409, json={"detail": "x"})).stream_turn(
                "s", "hi", None
            )
        )
    assert err.value.status == 409
    with pytest.raises(ApiError) as err:
        _client(lambda r: httpx.Response(429, json={"detail": "x"})).memories("a" * 16)
    assert err.value.status == 429

    def refuse(request):
        raise httpx.ConnectError("refused")

    with pytest.raises(ApiError) as err:
        list(_client(refuse).stream_turn("s", "hi", None))
    assert err.value.status is None


class DropAfterHeaders(httpx.SyncByteStream):
    def __iter__(self):
        yield b'event: token\ndata: {"text": "Hi"}\n\n'
        raise httpx.ReadError("connection dropped")


def test_api_error_says_whether_the_request_reached_the_server():
    def refuse(request):
        raise httpx.ConnectError("refused")

    with pytest.raises(ApiError) as err:
        list(_client(refuse).stream_approve("s", "t1", True))
    assert err.value.status is None and err.value.reached is False

    dropped = _client(lambda r: httpx.Response(200, stream=DropAfterHeaders()))
    with pytest.raises(ApiError) as err:
        list(dropped.stream_approve("s", "t1", True))
    assert err.value.status is None and err.value.reached is True

    with pytest.raises(ApiError) as err:
        list(_client(lambda r: httpx.Response(429, text="slow")).stream_approve("s", "t1", True))
    assert err.value.status == 429 and err.value.reached is True


def test_stream_quiz_posts_the_session_and_optional_learner():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"], seen["body"] = request.url.path, request.read().decode().replace(" ", "")
        return httpx.Response(200, text='event: done\ndata: {"ok": true}\n\n')

    client = _client(handler)
    assert list(client.stream_quiz("s")) == [("done", {"ok": True})]
    assert seen["path"] == "/v1/quiz" and seen["body"] == '{"session_id":"s"}'
    list(client.stream_quiz("s", learner_id="a" * 16))
    assert f'"learner_id":"{"a" * 16}"' in seen["body"]
