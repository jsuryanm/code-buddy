import random

from codebuddy.cache.memory import InMemoryCache
from codebuddy.metrics import Metrics
from codebuddy.pedagogy.judge import LeakJudge, Verdict, maybe_judge


class FakeChain:
    def __init__(self, verdict=None, fail=False):
        self.verdict, self.fail, self.calls = verdict, fail, []

    async def ainvoke(self, messages):
        self.calls.append(messages)
        if self.fail:
            raise RuntimeError("boom")
        return self.verdict


async def run(chain, rate=1.0, level=1, reply="Look at the loop header."):
    metrics = Metrics(InMemoryCache())
    verdict = await maybe_judge(
        LeakJudge(chain), metrics, rate, session_id="s", code="x", reply=reply, level=level
    )
    return verdict, await metrics.snapshot()


async def test_flagged_leak_is_counted():
    chain = FakeChain(Verdict(leaks_answer=True, reason="gives the exact change"))
    verdict, counts = await run(chain)
    assert verdict.leaks_answer and counts["judge_checked"] == 1 and counts["judge_flagged"] == 1
    assert "learner_code" in chain.calls[0][1][1]  # learner text is delimited as data


async def test_clean_reply_is_checked_but_not_flagged():
    _, counts = await run(FakeChain(Verdict(leaks_answer=False, reason="ok")))
    assert counts["judge_checked"] == 1 and counts["judge_flagged"] == 0


async def test_reveals_and_zero_rate_are_never_judged():
    chain = FakeChain(Verdict(leaks_answer=True, reason="x"))
    assert (await run(chain, level=4))[0] is None
    assert (await run(chain, rate=0.0))[0] is None
    assert not chain.calls


async def test_sampling_respects_the_rate():
    chain = FakeChain(Verdict(leaks_answer=False, reason="ok"))
    metrics = Metrics()
    rng = random.Random(1)
    for _ in range(200):
        await maybe_judge(
            LeakJudge(chain), metrics, 0.25, session_id="s", code=None, reply="r", level=0, rng=rng
        )
    assert 25 < len(chain.calls) < 75


async def test_judge_failure_never_raises():
    verdict, counts = await run(FakeChain(fail=True))
    assert verdict is None and counts["judge_checked"] == 0
