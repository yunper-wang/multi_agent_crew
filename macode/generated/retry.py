"""retry 模块:支持指数退避与异常类型过滤的重试装饰器。

功能特性
========
* 支持指定最大重试次数(``max_retries``,不含首次调用);
* 支持指数退避间隔:第 n 次重试前等待 ``base_delay * backoff_factor ** (n - 1)``
  秒,可用 ``max_delay`` 设置单次等待上限,``jitter`` 开启随机抖动;
* 只对 ``exceptions`` 指定的异常类型(及其子类)重试,其余异常直接抛出;
* 使用 ``functools.wraps`` 保留被装饰函数的元信息。

使用示例
========
>>> from retry import retry
>>>
>>> @retry(max_retries=3, base_delay=0.1, backoff_factor=2.0,
...        exceptions=(ConnectionError, TimeoutError))
... def fetch_data() -> str:
...     return "data"

运行测试
========
* ``python -m pytest retry.py -v``  # 运行全部 pytest 单元测试
* ``python retry.py``               # 直接运行:有 pytest 则执行测试,否则做冒烟自检
"""

from __future__ import annotations

import functools
import logging
import random
import time
from typing import Any, Callable, Optional, Tuple, Type, TypeVar, Union

__all__ = ["retry"]
__version__ = "1.0.0"

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])

# 允许传入单个异常类或异常类元组
_ExceptionTypes = Union[Type[BaseException], Tuple[Type[BaseException], ...]]


def retry(
    max_retries: int = 3,
    base_delay: float = 0.5,
    backoff_factor: float = 2.0,
    max_delay: Optional[float] = None,
    exceptions: _ExceptionTypes = (Exception,),
    jitter: bool = False,
) -> Callable[[F], F]:
    """构建一个"按指数退避重试"的装饰器。

    退避策略:第 ``n`` 次重试(``n`` 从 1 开始)前等待
    ``base_delay * backoff_factor ** (n - 1)`` 秒,且不超过 ``max_delay``;
    开启 ``jitter`` 后实际等待时间为 ``[0, 计算值]`` 内的均匀随机值。

    :param max_retries: 最大重试次数(不含首次调用),必须为非负整数。
        如 ``max_retries=3`` 表示最多共调用 4 次(1 次原始调用 + 3 次重试)。
    :param base_delay: 基础退避间隔(秒),必须 >= 0。
    :param backoff_factor: 退避因子,必须 >= 1;为 1 时退化为固定间隔。
    :param max_delay: 单次等待时间上限(秒);``None`` 表示不设上限。
    :param exceptions: 触发重试的异常类型(单个异常类或异常类元组),
        其子类异常同样会被重试;其余异常不做任何重试,直接向上抛出。
    :param jitter: 是否加入随机抖动以避免"惊群效应"。
    :returns: 装饰器,应用于目标函数后返回包装函数。
    :raises ValueError: 当参数非法时抛出。

    使用示例::

        @retry(max_retries=3, base_delay=0.1, exceptions=(ConnectionError,))
        def fetch() -> str:
            ...
    """
    if (
        isinstance(max_retries, bool)
        or not isinstance(max_retries, int)
        or max_retries < 0
    ):
        raise ValueError(f"max_retries 必须是非负整数,当前值: {max_retries!r}")
    if base_delay < 0:
        raise ValueError(f"base_delay 必须 >= 0,当前值: {base_delay!r}")
    if backoff_factor < 1:
        raise ValueError(f"backoff_factor 必须 >= 1,当前值: {backoff_factor!r}")
    if max_delay is not None and max_delay < 0:
        raise ValueError(f"max_delay 必须 >= 0 或为 None,当前值: {max_delay!r}")

    # 兼容直接传入单个异常类的写法
    if isinstance(exceptions, type):
        if not issubclass(exceptions, BaseException):
            raise ValueError(f"exceptions 必须是异常类型,当前值: {exceptions!r}")
        exceptions = (exceptions,)
    if not isinstance(exceptions, tuple) or len(exceptions) == 0:
        raise ValueError("exceptions 必须是非空的异常类型元组")
    for exc_type in exceptions:
        if not (isinstance(exc_type, type) and issubclass(exc_type, BaseException)):
            raise ValueError(
                f"exceptions 的元素必须是异常类型,当前值: {exc_type!r}"
            )

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            attempt = 0  # 已进行的重试次数
            while True:
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    if attempt >= max_retries:
                        logger.error(
                            "函数 %s 已重试 %d 次仍失败,放弃重试: %r",
                            func.__qualname__,
                            attempt,
                            exc,
                        )
                        raise
                    delay = base_delay * (backoff_factor ** attempt)
                    if max_delay is not None:
                        delay = min(delay, max_delay)
                    if jitter:
                        delay = random.uniform(0.0, delay)
                    attempt += 1
                    logger.warning(
                        "函数 %s 第 %d 次重试(原因: %r),等待 %.3f 秒",
                        func.__qualname__,
                        attempt,
                        exc,
                        delay,
                    )
                    if delay > 0:
                        time.sleep(delay)

        return wrapper  # type: ignore[return-value]

    return decorator


# ===========================================================================
# pytest 单元测试
# 运行方式: python -m pytest retry.py -v
# ===========================================================================
try:
    import pytest
except ImportError:  # pragma: no cover - 未安装 pytest 时跳过测试定义
    pytest = None  # type: ignore[assignment]


if pytest is not None:

    class TestRetryBasic:
        """基本重试行为。"""

        def test_success_on_first_call(self) -> None:
            calls = {"n": 0}

            @retry(max_retries=3, base_delay=0)
            def ok() -> str:
                calls["n"] += 1
                return "ok"

            assert ok() == "ok"
            assert calls["n"] == 1

        def test_success_after_failures(self) -> None:
            calls = {"n": 0}

            @retry(max_retries=3, base_delay=0, exceptions=(ConnectionError,))
            def flaky() -> str:
                calls["n"] += 1
                if calls["n"] < 3:
                    raise ConnectionError("network down")
                return "recovered"

            assert flaky() == "recovered"
            assert calls["n"] == 3

        def test_args_and_kwargs_passthrough(self) -> None:
            @retry(max_retries=1, base_delay=0)
            def add(a: int, b: int = 0) -> int:
                return a + b

            assert add(2, b=3) == 5

        def test_wraps_preserves_metadata(self) -> None:
            @retry()
            def documented() -> None:
                """示例文档字符串。"""

            assert documented.__name__ == "documented"
            assert documented.__doc__ == "示例文档字符串。"

        def test_subclass_exception_is_retried(self) -> None:
            calls = {"n": 0}

            @retry(max_retries=2, base_delay=0, exceptions=(OSError,))
            def maybe_fail() -> str:
                calls["n"] += 1
                if calls["n"] == 1:
                    raise FileNotFoundError("missing file")  # OSError 子类
                return "done"

            assert maybe_fail() == "done"
            assert calls["n"] == 2

        def test_single_exception_class_accepted(self) -> None:
            calls = {"n": 0}

            @retry(
                max_retries=1,
                base_delay=0,
                exceptions=ConnectionError,  # type: ignore[arg-type]
            )
            def maybe_fail() -> str:
                calls["n"] += 1
                if calls["n"] == 1:
                    raise ConnectionError("down")
                return "up"

            assert maybe_fail() == "up"
            assert calls["n"] == 2

    class TestExceptionFilter:
        """异常类型过滤:仅指定异常重试,其余直接抛出。"""

        def test_unlisted_exception_raised_immediately(self) -> None:
            calls = {"n": 0}

            @retry(max_retries=5, base_delay=0, exceptions=(ConnectionError,))
            def boom() -> None:
                calls["n"] += 1
                raise ValueError("not retryable")

            with pytest.raises(ValueError, match="not retryable"):
                boom()
            assert calls["n"] == 1  # 未发生任何重试

        def test_give_up_after_max_retries(self) -> None:
            calls = {"n": 0}

            @retry(max_retries=3, base_delay=0, exceptions=(ConnectionError,))
            def always_fail() -> None:
                calls["n"] += 1
                raise ConnectionError("still down")

            with pytest.raises(ConnectionError, match="still down"):
                always_fail()
            assert calls["n"] == 4  # 1 次原始调用 + 3 次重试

        def test_zero_max_retries_means_no_retry(self) -> None:
            calls = {"n": 0}

            @retry(max_retries=0, base_delay=0)
            def fail() -> None:
                calls["n"] += 1
                raise RuntimeError("boom")

            with pytest.raises(RuntimeError, match="boom"):
                fail()
            assert calls["n"] == 1

    class TestExponentialBackoff:
        """指数退避间隔行为(通过 monkeypatch 记录 time.sleep 的调用)。"""

        def test_exponential_backoff_delays(
            self, monkeypatch: pytest.MonkeyPatch
        ) -> None:
            sleeps: list[float] = []
            monkeypatch.setattr(time, "sleep", sleeps.append)

            @retry(
                max_retries=3,
                base_delay=1.0,
                backoff_factor=2.0,
                exceptions=(RuntimeError,),
            )
            def always_fail() -> None:
                raise RuntimeError("x")

            with pytest.raises(RuntimeError):
                always_fail()

            assert sleeps == [1.0, 2.0, 4.0]  # 1*2^0, 1*2^1, 1*2^2

        def test_max_delay_caps_wait(
            self, monkeypatch: pytest.MonkeyPatch
        ) -> None:
            sleeps: list[float] = []
            monkeypatch.setattr(time, "sleep", sleeps.append)

            @retry(
                max_retries=3,
                base_delay=1.0,
                backoff_factor=10.0,
                max_delay=5.0,
                exceptions=(RuntimeError,),
            )
            def always_fail() -> None:
                raise RuntimeError("x")

            with pytest.raises(RuntimeError):
                always_fail()

            assert sleeps == [1.0, 5.0, 5.0]

        def test_jitter_within_bounds(
            self, monkeypatch: pytest.MonkeyPatch
        ) -> None:
            sleeps: list[float] = []
            monkeypatch.setattr(time, "sleep", sleeps.append)

            @retry(
                max_retries=5,
                base_delay=1.0,
                backoff_factor=2.0,
                jitter=True,
                exceptions=(RuntimeError,),
            )
            def always_fail() -> None:
                raise RuntimeError("x")

            with pytest.raises(RuntimeError):
                always_fail()

            assert len(sleeps) == 5
            for index, delay in enumerate(sleeps):
                assert 0.0 <= delay <= 1.0 * (2.0 ** index)

    class TestParameterValidation:
        """非法参数校验。"""

        @pytest.mark.parametrize(
            "kwargs",
            [
                {"max_retries": -1},
                {"max_retries": 1.5},
                {"max_retries": True},
                {"base_delay": -0.1},
                {"backoff_factor": 0.5},
                {"max_delay": -1.0},
                {"exceptions": ()},
                {"exceptions": (123,)},
                {"exceptions": int},
            ],
        )
        def test_invalid_params_raise_value_error(self, kwargs: dict) -> None:
            with pytest.raises(ValueError):
                retry(**kwargs)

        def test_valid_params_do_not_raise(self) -> None:
            retry(
                max_retries=0,
                base_delay=0.0,
                backoff_factor=1.0,
                max_delay=None,
                exceptions=(Exception,),
                jitter=False,
            )


def _smoke_test() -> None:
    """不依赖 pytest 的最小化自检。"""
    calls = {"n": 0}

    @retry(max_retries=2, base_delay=0, exceptions=(ValueError,))
    def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 2:
            raise ValueError("临时失败")
        return "ok"

    assert flaky() == "ok", "重试后应返回正确结果"
    assert calls["n"] == 2, "应恰好调用 2 次"

    @retry(max_retries=3, base_delay=0, exceptions=(KeyError,))
    def wrong_exc() -> None:
        raise TypeError("不在重试列表中")

    try:
        wrong_exc()
    except TypeError:
        pass
    else:  # pragma: no cover
        raise AssertionError("未在重试列表中的异常应直接抛出")

    print("[retry.py] 冒烟自检通过(未检测到 pytest,仅执行基本检查)。")
    print("[retry.py] 安装 pytest 后可运行完整测试: python -m pytest retry.py -v")


if __name__ == "__main__":
    if pytest is not None:
        raise SystemExit(pytest.main([__file__, "-v"]))
    _smoke_test()
