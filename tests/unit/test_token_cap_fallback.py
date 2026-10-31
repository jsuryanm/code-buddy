"""The per-call token cap must reach every tier of a with_fallbacks chain."""

from langchain_core.messages import AIMessageChunk
from langchain_core.runnables import Runnable


class Recorder(Runnable):
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.kwargs: list[dict] = []

    def invoke(self, input, config=None, **kwargs):
        raise NotImplementedError

    async def astream(self, input, config=None, **kwargs):
        self.kwargs.append(kwargs)
        if self.fail:
            raise RuntimeError("primary down")
        yield AIMessageChunk(content="ok")


async def test_cap_passed_to_astream_reaches_the_fallback_tier():
    primary, fallback = Recorder(fail=True), Recorder()
    chain = primary.with_fallbacks([fallback])
    out = [c async for c in chain.astream([("human", "hi")], max_completion_tokens=250)]
    assert out and primary.kwargs == [{"max_completion_tokens": 250}]
    assert fallback.kwargs == [{"max_completion_tokens": 250}]


def test_chat_openai_turns_the_kwarg_into_the_request_cap():
    from langchain_openai import ChatOpenAI

    payload = ChatOpenAI(model="m", api_key="k")._get_request_payload(
        [("human", "hi")], max_completion_tokens=250
    )
    assert payload["max_completion_tokens"] == 250
