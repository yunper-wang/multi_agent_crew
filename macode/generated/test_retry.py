"""retry 装饰器实现及 pytest 单元测试。

需求:
    1. 支持指定最大重试次数;
    2. 支持指数退避间隔;
    3. 只对指定异常类型重试,其余异常直接抛出。

运行方式:
    pytest test_retry.py -v
    或直接执行: python test_retry.py
"""

import functools
import time

import pytest

__all__ = ["retry"]


def retry(max_attempts=3, backoff_factor=1.0, exceptions=(Exception,)):
    """指数退避重试装饰器。

    :param max_attempts: 最大尝试次数(包含首次调用),必须为 >= 1 的整数。
    :param backoff_factor: 退避基数(秒)。第 n 次重试前休眠
        ``backoff_factor * 2 ** (n - 1)`` 秒(1x、2x、4x…… 指数增长);
        取 0 表示重试前不休眠。
    :param exceptions: 触发重试的异常类型(可传单个类型或类型元组);
        不在其中的异常不做重试,直接向上抛出。
    :raises ValueError: max_attempts 或 backoff_factor 取值非法。
    :raises TypeError: exceptions 不是异常类型。
    :returns: 装饰器函数。
    """
    if (
        not isinstance(max_attempts, int)
        or isinstance(max_attempts, bool)
        or max_attempts < 1
    ):
        raise ValueError("max_attempts 必须是 >= 1 的整数")
    if (
        not isinstance(backoff_factor, (int, float))
        or isinstance(backoff_factor, bool)
        or backoff_factor < 0
    ):
        raise ValueError("backoff_factor 必须是 >= 0 的数值")
    if not isinstance(exceptions, tuple):
        exceptions = (exceptions,)
    if not exceptions or not all(
        isinstance(exc, type) and issubclass(exc, BaseException)
        for exc in exceptions
    ):
        raise TypeError("exceptions 必须是异常类型或异常类型元组")

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions:
                    # 次数耗尽:抛出最后一次异常,保留原始 traceback
                    if attempt >= max_attempts:
                        raise
                    # 指数退避:base * 2^(attempt-1)
                    delay = backoff_factor * (2 ** (attempt - 1))
                    if delay > 0:
                        time.sleep(delay)
            # 循环必然以 return 或 raise 结束,此处不可达
            raise RuntimeError("unreachable")  # pragma: no cover

        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# 测试辅助
# ---------------------------------------------------------------------------


class FlakyError(Exception):
    """测试中使用的自定义异常。"""


def make_flaky(fail_times, exc_factory=FlakyError, success_value="ok"):
    """构造一个前 fail_times 次调用抛异常、之后返回 success_value 的函数。

    :returns: (func, state),state["calls"] 记录实际调用次数。
    """
    state = {"calls": 0}

    def func():
        state["calls"] += 1
        if state["calls"] <= fail_times:
            raise exc_factory("fail #{}".format(state["calls"]))
        return success_value

    return func, state


# ---------------------------------------------------------------------------
# 单元测试
# ---------------------------------------------------------------------------


class TestRetryBehaviour:
    """核心重试逻辑。"""

    def test_success_first_try_no_retry(self):
        func, state = make_flaky(fail_times=0)
        decorated = retry(max_attempts=3, backoff_factor=0)(func)
        assert decorated() == "ok"
        assert state["calls"] == 1

    def test_success_after_retries(self):
        func, state = make_flaky(fail_times=2)
        decorated = retry(
            max_attempts=3, backoff_factor=0, exceptions=(FlakyError,)
        )(func)
        assert decorated() == "ok"
        assert state["calls"] == 3

    def test_exhaust_attempts_raises_last_exception(self):
        func, state = make_flaky(fail_times=99)
        decorated = retry(
            max_attempts=4, backoff_factor=0, exceptions=(FlakyError,)
        )(func)
        with pytest.raises(FlakyError, match="fail #4"):
            decorated()
        assert state["calls"] == 4

    def test_max_attempts_one_means_no_retry(self):
        func, state = make_flaky(fail_times=1)
        decorated = retry(
            max_attempts=1, backoff_factor=0, exceptions=(FlakyError,)
        )(func)
        with pytest.raises(FlakyError):
            decorated()
        assert state["calls"] == 1


class TestExceptionFiltering:
    """仅对指定异常类型重试,其余异常直接抛出。"""

    def test_unmatched_exception_propagates_without_retry(self):
        state = {"calls": 0}

        @retry(max_attempts=5, backoff_factor=0, exceptions=(ValueError,))
        def func():
            state["calls"] += 1
            raise TypeError("not retryable")

        with pytest.raises(TypeError, match="not retryable"):
            func()
        assert state["calls"] == 1  # 未重试,仅调用一次

    def test_exception_subclass_is_retried(self):
        class SubFlaky(FlakyError):
            pass

        func, state = make_flaky(fail_times=2, exc_factory=SubFlaky)
        decorated = retry(
            max_attempts=3, backoff_factor=0, exceptions=(FlakyError,)
        )(func)
        assert decorated() == "ok"
        assert state["calls"] == 3

    def test_multiple_exception_types(self):
        state = {"calls": 0}
        errors = [ValueError, KeyError, FlakyError]

        @retry(max_attempts=5, backoff_factor=0, exceptions=(ValueError, KeyError))
        def func():
            state["calls"] += 1
            raise errors[state["calls"] - 1]("boom")

        # 第三次抛出 FlakyError,不在重试白名单,应直接抛出
        with pytest.raises(FlakyError):
            func()
        assert state["calls"] == 3

    def test_single_exception_type_without_tuple(self):
        func, state = make_flaky(fail_times=1)
        decorated = retry(max_attempts=2, backoff_factor=0, exceptions=FlakyError)(func)
        assert decorated() == "ok"
        assert state["calls"] == 2


class TestExponentialBackoff:
    """指数退避间隔。"""

    def test_backoff_delays_grow_exponentially(self, monkeypatch):
        sleeps = []
        monkeypatch.setattr(time, "sleep", sleeps.append)

        func, state = make_flaky(fail_times=99)
        decorated = retry(
            max_attempts=4, backoff_factor=0.5, exceptions=(FlakyError,)
        )(func)
        with pytest.raises(FlakyError):
            decorated()

        assert state["calls"] == 4
        # 退避序列:0.5 -> 1.0 -> 2.0;最后一次失败后不再休眠
        assert sleeps == [0.5, 1.0, 2.0]

    def test_zero_backoff_never_sleeps(self, monkeypatch):
        sleeps = []
        monkeypatch.setattr(time, "sleep", sleeps.append)

        func, _ = make_flaky(fail_times=99)
        decorated = retry(
            max_attempts=3, backoff_factor=0, exceptions=(FlakyError,)
        )(func)
        with pytest.raises(FlakyError):
            decorated()
        assert sleeps == []


class TestDecoratorSemantics:
    """装饰器行为细节。"""

    def test_preserves_metadata(self):
        @retry()
        def sample(a, b):
            """示例函数。"""
            return a + b

        assert sample.__name__ == "sample"
        assert sample.__doc__ == "示例函数。"
        assert sample(2, 3) == 5

    def test_passes_args_and_kwargs(self):
        seen = {}

        @retry(max_attempts=2, backoff_factor=0)
        def func(a, b=0, *, c=0):
            seen.update(a=a, b=b, c=c)
            return a + b + c

        assert func(1, 2, c=3) == 6
        assert seen == {"a": 1, "b": 2, "c": 3}


class TestParameterValidation:
    """装饰器参数校验。"""

    @pytest.mark.parametrize("bad", [0, -1, 2.5, "3", None, True])
    def test_invalid_max_attempts(self, bad):
        with pytest.raises(ValueError):
            retry(max_attempts=bad)

    @pytest.mark.parametrize("bad", [-0.1, -1, "1", None, False])
    def test_invalid_backoff_factor(self, bad):
        with pytest.raises(ValueError):
            retry(backoff_factor=bad)

    @pytest.mark.parametrize("bad", [(int,), (), 42, [ValueError]])
    def test_invalid_exceptions(self, bad):
        with pytest.raises(TypeError):
            retry(exceptions=bad)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
