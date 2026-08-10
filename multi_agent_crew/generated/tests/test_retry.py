"""retry 装饰器的单元测试。

只通过公开接口与可观察行为(返回值、调用次数、sleep 间隔、异常)
进行断言,不依赖任何内部实现细节;所有用例均不发生真实等待。
"""

import pytest

import retry as retry_module
from retry import retry


@pytest.fixture
def sleep_log(monkeypatch):
    """将 time.sleep 替换为记录型 fake,返回等待间隔的列表。"""
    calls: list[float] = []
    monkeypatch.setattr(retry_module.time, "sleep", calls.append)
    return calls


def test_success_on_first_call(sleep_log):
    """正常路径:首次即成功,不重试、不等待。"""
    calls = []

    @retry()
    def add(a, b):
        calls.append((a, b))
        return a + b

    assert add(1, 2) == 3
    assert len(calls) == 1
    assert sleep_log == []


def test_success_after_retries(sleep_log):
    """前 2 次抛白名单异常,第 3 次成功并返回结果。"""
    count = 0

    @retry(max_attempts=3, base_delay=0, retry_exceptions=(ConnectionError,))
    def flaky():
        nonlocal count
        count += 1
        if count < 3:
            raise ConnectionError("连接失败")
        return "ok"

    assert flaky() == "ok"
    assert count == 3


def test_retry_exhausted_raises_original_exception(sleep_log):
    """重试耗尽:原样抛出原始异常,调用次数恰好等于 max_attempts。"""
    count = 0

    @retry(max_attempts=3, base_delay=0, retry_exceptions=(ConnectionError,))
    def always_fail():
        nonlocal count
        count += 1
        raise ConnectionError("连接被拒绝")

    with pytest.raises(ConnectionError, match="连接被拒绝"):
        always_fail()
    assert count == 3


def test_non_whitelisted_exception_propagates_without_retry(sleep_log):
    """非白名单异常:不重试、不等待,直接向上抛出。"""
    count = 0

    @retry(max_attempts=5, retry_exceptions=(ConnectionError,))
    def raises_value_error():
        nonlocal count
        count += 1
        raise ValueError("不在白名单内")

    with pytest.raises(ValueError, match="不在白名单内"):
        raises_value_error()
    assert count == 1
    assert sleep_log == []


def test_backoff_intervals_when_eventually_succeeds(sleep_log):
    """指数退避(成功收尾):间隔为 base_delay * backoff ** attempt。"""
    count = 0

    @retry(max_attempts=4, base_delay=0.5, backoff=2.0, retry_exceptions=(ConnectionError,))
    def flaky():
        nonlocal count
        count += 1
        if count < 4:
            raise ConnectionError("再试一次")
        return "ok"

    assert flaky() == "ok"
    assert sleep_log == [0.5, 1.0, 2.0]


def test_backoff_intervals_when_exhausted(sleep_log):
    """指数退避(失败收尾):间隔序列与成功收尾一致,最后一次失败后不再等待。"""

    @retry(max_attempts=4, base_delay=0.5, backoff=2.0, retry_exceptions=(ConnectionError,))
    def always_fail():
        raise ConnectionError("始终失败")

    with pytest.raises(ConnectionError, match="始终失败"):
        always_fail()
    assert sleep_log == [0.5, 1.0, 2.0]


@pytest.mark.parametrize(
    ("kwargs", "param_name"),
    [
        ({"max_attempts": 0}, "max_attempts"),
        ({"base_delay": -1}, "base_delay"),
        ({"backoff": 0.5}, "backoff"),
    ],
)
def test_invalid_params_raise_value_error_at_definition(kwargs, param_name):
    """参数非法:定义装饰器时即抛 ValueError,错误信息包含参数名。"""
    with pytest.raises(ValueError, match=param_name):
        retry(**kwargs)


def test_wraps_preserves_metadata():
    """装饰后函数的 __name__/__doc__ 与原函数一致(functools.wraps)。"""

    @retry()
    def my_function():
        """示例文档字符串。"""
        return 1

    assert my_function.__name__ == "my_function"
    assert my_function.__doc__ == "示例文档字符串。"
