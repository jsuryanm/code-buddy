from codebuddy.eval.run import check, evaluate


async def test_offline_eval_meets_all_thresholds():
    metrics = await evaluate()
    assert check(metrics) == [], metrics
    assert metrics["leak_rate"] == 0 and metrics["guard_trigger_rate"] == 1.0
