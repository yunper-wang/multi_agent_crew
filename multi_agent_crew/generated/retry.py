"""通用重试装饰器:对指定异常类型按指数退避策略重试,其余异常直接抛出。

仅依赖标准库,支持 Python 3.10+(使用 typing.ParamSpec 保留被装饰函数签名)。
"""

from __future__ import annotations

import functools
import time
from typing import Callable, ParamSpec, TypeVar

# ParamSpec/TypeVar 用于让装饰器"透传"被装饰函数的参数与返回类型,
# 避免装饰后丢失静态类型信息
P = ParamSpec("P")
T = TypeVar("T")


def retry(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """装饰器工厂:对指定异常按指数退避重试,不在列表内的异常立即上抛。

    参数:
        max_attempts: 最大尝试次数(含首次调用),必须 >= 1。
        base_delay: 首次重试前的休眠秒数,必须 >= 0;之后每次重试翻倍。
        exceptions: 触发重试的异常类型元组,任一命中即重试;
            不在其中的异常不重试、直接向上传播。

    返回:
        装饰器,用法为 @retry(...);被装饰函数的签名与元数据保持不变。

    抛出:
        ValueError: max_attempts < 1 或 base_delay < 0 时,在装饰阶段即报错,
            让配置错误尽早暴露,而不是等到运行期才失败。
    """
    if max_attempts < 1:
        raise ValueError(f"max_attempts 必须 >= 1,当前值: {max_attempts!r}")
    if base_delay < 0:
        raise ValueError(f"base_delay 必须 >= 0,当前值: {base_delay!r}")

    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @functools.wraps(func)  # 保留 __name__/__doc__ 等元数据,便于调试与内省
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions:
                    if attempt == max_attempts:
                        # 裸 raise 重新抛出当前异常,保留原始 traceback 以便定位根因
                        raise
                    # 指数退避(第 n 次失败后等 base_delay * 2**(n-1),即 1s、2s、4s…):
                    # 给瞬时故障(网络抖动、限流)留出恢复时间,同时避免固定间隔
                    # 让多个调用方在同一时刻"撞车"式重试
                    time.sleep(base_delay * 2 ** (attempt - 1))
            # 逻辑上不可达:循环只能以 return 或 raise 结束;
            # 保留此行仅为满足类型检查器对"所有路径都有返回"的要求
            raise AssertionError("unreachable")  # pragma: no cover

        return wrapper

    return decorator
