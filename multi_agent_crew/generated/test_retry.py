"""retry 装饰器的单元测试:覆盖正常路径、边界情况与指数退避时序。

测试只依赖公开接口(from retry import retry),不断言内部实现细节。
除退避时序用例外,统一使用 base_delay=0 避免真实等待。
"""

from __future__ import annotations

import pytest

from retry import retry


class TestSuccessPath:
    """正常路径:成功时不重试,返回值原样透传。"""

    def test_no_retry_when_first_call_succeeds(self) -> None:
        calls: list[tuple[int, int]] = []

        @retry(max_attempts=3, base_delay=0)
        def add(a: int, b: int) -> int:
            calls.append((a, b))
            return a + b

        assert add(1, 2) == 3
        assert len(calls) == 1  # 一次成功不应触发任何重试

    def test_succeeds_after_transient_failures(self) -> None:
        state = {"calls": 0}

        @retry(max_attempts=3, base_delay=0)
        def flaky() -> str:
            state["calls"] += 1
            if state["calls"] < 3:
                raise ConnectionError(f"第 {state['calls']} 次暂时不可用")
            return "ok"

        assert flaky() == "ok"
        assert state["calls"] == 3  # 前 2 次失败 + 第 3 次成功

    def test_positional_and_keyword_args_pass_through(self) -> None:
        @retry(base_delay=0)
        def greet(name: str, punctuation: str = "!") -> str:
            return f"hello {name}{punctuation}"

        assert greet("world", punctuation="?") == "hello world?"


class TestRetryExhaustion:
    """边界:重试次数耗尽 / 异常类型不命中。"""

    def test_reraises_last_exception_after_max_attempts(self) -> None:
        state = {"calls": 0}

        @retry(max_attempts=3, base_delay=0)
        def always_fail() -> None:
            state["calls"] += 1
            raise RuntimeError(f"第 {state['calls']} 次失败")

        # 抛出的应是"最后一次"的原始异常(类型与消息均一致)
        with pytest.raises(RuntimeError, match="第 3 次失败"):
            always_fail()
        assert state["calls"] == 3  # 总调用次数 == max_attempts

    def test_unlisted_exception_propagates_immediately(self) -> None:
        state = {"calls": 0}

        @retry(max_attempts=5, base_delay=0, exceptions=(ValueError,))
        def raise_key_error() -> None:
            state["calls"] += 1
            raise KeyError("不在重试列表中")

        with pytest.raises(KeyError):
            raise_key_error()
        assert state["calls"] == 1  # 未命中 exceptions,不重试、直接上抛


class TestBackoffTiming:
    """退避时序:monkeypatch 替换 retry 模块内的 time.sleep,验证指数序列。"""

    def test_exponential_backoff_delays(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sleeps: list[float] = []
        monkeypatch.setattr("retry.time.sleep", sleeps.append)

        @retry(max_attempts=4, base_delay=1.0, exceptions=(ValueError,))
        def always_fail() -> None:
            raise ValueError("boom")

        with pytest.raises(ValueError):
            always_fail()
        # 第 1/2/3 次失败后分别休眠 1s、2s、4s;第 4 次失败直接抛出,不再休眠
        assert sleeps == [1.0, 2.0, 4.0]

    def test_base_delay_scales_backoff(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sleeps: list[float] = []
        monkeypatch.setattr("retry.time.sleep", sleeps.append)

        @retry(max_attempts=3, base_delay=0.5)
        def always_fail() -> None:
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError):
            always_fail()
        assert sleeps == [0.5, 1.0]

    def test_no_sleep_after_final_attempt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sleeps: list[float] = []
        monkeypatch.setattr("retry.time.sleep", sleeps.append)

        @retry(max_attempts=1, base_delay=1.0)
        def fail_once() -> None:
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError):
            fail_once()
        assert sleeps == []  # 仅 1 次机会时失败即抛出,不应发生任何休眠


class TestMetadata:
    """元数据:functools.wraps 应保留 __name__ 与 __doc__。"""

    def test_wraps_preserves_name_and_doc(self) -> None:
        @retry(base_delay=0)
        def my_func() -> int:
            """这是文档字符串。"""
            return 1

        assert my_func.__name__ == "my_func"
        assert my_func.__doc__ == "这是文档字符串。"


class TestParamValidation:
    """边界:非法参数在装饰阶段即抛出 ValueError。"""

    def test_zero_max_attempts_raises(self) -> None:
        with pytest.raises(ValueError, match="max_attempts"):
            retry(max_attempts=0)

    def test_negative_max_attempts_raises(self) -> None:
        with pytest.raises(ValueError, match="max_attempts"):
            retry(max_attempts=-2)

    def test_negative_base_delay_raises(self) -> None:
        with pytest.raises(ValueError, match="base_delay"):
            retry(base_delay=-1)


class TestMultipleExceptions:
    """exceptions 传入多类型元组时,任一命中均触发重试。"""

    @pytest.mark.parametrize("exc_type", [ValueError, TypeError])
    def test_any_listed_exception_triggers_retry(
        self, exc_type: type[Exception]
    ) -> None:
        state = {"calls": 0}

        @retry(max_attempts=3, base_delay=0, exceptions=(ValueError, TypeError))
        def fail_once_then_succeed() -> str:
            state["calls"] += 1
            if state["calls"] == 1:
                raise exc_type("命中其一")
            return "ok"

        assert fail_once_then_succeed() == "ok"
        assert state["calls"] == 2
