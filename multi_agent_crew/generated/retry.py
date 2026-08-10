"""支持最大重试次数、指数退避、按异常类型选择性重试的 retry 装饰器。

仅依赖标准库,要求 Python >= 3.10(typing.ParamSpec)。
"""

from __future__ import annotations

import functools
import time
from typing import Callable, ParamSpec, TypeVar

P = ParamSpec("P")
T = TypeVar("T")


def retry(
    max_attempts: int = 3,
    base_delay: float = 0.5,
    backoff: float = 2.0,
    retry_exceptions: tuple[type[BaseException], ...] = (Exception,),
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """重试装饰器工厂:为被装饰函数附加指数退避重试逻辑。

    仅支持带括号用法(``@retry()`` 或 ``@retry(max_attempts=5)``),
    借此消除裸 ``@retry`` 的特殊情况。

    参数:
        max_attempts: 最大尝试次数(含首次调用),必须 >= 1。
        base_delay: 首次重试前的等待秒数,必须 >= 0;传 0 表示不等待。
        backoff: 退避乘数,必须 >= 1;第 n 次重试前等待
            ``base_delay * backoff ** (n - 1)`` 秒。
        retry_exceptions: 触发重试的异常类型白名单;不在白名单内的异常
            不做任何捕获,直接向上传播。

    返回:
        装饰器。被装饰函数的签名与元信息(__name__/__doc__)保持不变。

    异常:
        ValueError: 参数非法时在装饰器定义阶段立即抛出,让错误尽早暴露,
            而不是等到被装饰函数第一次被调用时才失败。
        被装饰函数自身的异常:重试耗尽或异常不在白名单时原样抛出。
    """
    if max_attempts < 1:
        raise ValueError(f"max_attempts 必须 >= 1,当前取值: {max_attempts!r}")
    if base_delay < 0:
        raise ValueError(f"base_delay 必须 >= 0,当前取值: {base_delay!r}")
    if backoff < 1:
        raise ValueError(f"backoff 必须 >= 1,当前取值: {backoff!r}")

    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except retry_exceptions:
                    # 最后一次尝试失败时必须原样 raise:此时已没有重试机会,
                    # 若吞掉异常或改抛别的异常,调用方将丢失真实的失败原因。
                    if attempt == max_attempts - 1:
                        raise
                    # 通过模块级 time.sleep 调用,方便测试用 monkeypatch 替换。
                    time.sleep(base_delay * backoff**attempt)

        return wrapper

    return decorator
