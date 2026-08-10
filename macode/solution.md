两个文件语法复核均通过，pytest 复跑 14/14 通过（0.02s)。逐行审查后未发现需要修正的功能性缺陷，以下为最终交付的 solution.md 完整内容：

---

# retry 装饰器 — 最终交付方案

## 一、最终代码

### generated/retry.py

```python
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
```

### generated/test_retry.py

```python
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
```

## 二、测试结论（复跑验证）

- **语法复核**:`python_syntax_check` 对 `retry.py`、`test_retry.py` 逐一通过 ast 静态解析，均无语法错误。
- **pytest 复跑**:`pytest test_retry.py -v`，退出码 **0**,**14 passed in 0.02s**,0 失败、0 跳过、0 警告（Python 3.13.13,pytest 9.1.1)。
- 覆盖分布：正常路径 3 例、耗尽/不命中 2 例、退避时序 3 例（含 `max_attempts=1` 零休眠边界）、元数据 1 例、参数校验 3 例、多异常参数化 2 例。
- 此前的真实时钟冒烟测试亦佐证：base_delay=0.1、3 次尝试实测耗时 0.306s，与理论 0.3s 吻合，指数退避在真实 `time.sleep` 下按预期工作。

## 三、评审说明

**结论：未发现需要修正的缺陷，代码按原样交付。** 审查中重点核对项与结论如下：

1. **正确性（对照测试结论逐项核实）**
   - 退避公式 `base_delay * 2 ** (attempt - 1)`：`attempt` 从 1 起计数，第 1/2/3 次失败后分别休眠 1×、2×、4× base_delay，与测试断言的 `[1.0, 2.0, 4.0]`、`[0.5, 1.0]` 精确一致；最后一次失败走 `attempt == max_attempts` 分支直接裸 `raise`，**不再休眠**，由 `test_no_sleep_after_final_attempt` 证实。
   - 裸 `raise` 位于 `except` 块内，重新抛出当前异常并保留原始 traceback；耗尽后抛出的是"最后一次"异常（消息为"第 3 次失败")，测试已用 `pytest.raises(..., match=...)` 同时锁定类型与消息。
   - 未命中 `exceptions` 的异常不经 `except` 子句，自然向上传播、零重试，符合"无裸 except、不重试"的要求。
   - 默认 `exceptions=(Exception,)` 不会误吞 `KeyboardInterrupt`/`SystemExit`（它们继承自 `BaseException`)，是合理的默认选择。

2. **边界处理**
   - `max_attempts=1`：循环仅执行一次，失败即抛、无休眠，已被专门用例覆盖。
   - `base_delay=0`:`sleep(0)` 无害，测试借此避免真实等待，套件整体 0.02s 完成。
   - 参数校验在**装饰阶段**（调用 `retry(...)` 时）而非首次调用时抛 `ValueError`，错误信息带当前值上下文，配置错误尽早暴露。
   - 已知非问题（经评估不改）：`exceptions=()` 时 `except ()` 合法且永不命中，语义等价于"禁用重试"，属可接受配置；非整数的 `max_attempts`(如 2.5）会由 `range()` 抛出信息明确的 `TypeError`——类型注解已声明契约，额外加 `isinstance` 校验属过度设计，且规格仅要求 `< 1` 时抛 `ValueError`，故不加固。

3. **可维护性**
   - `functools.wraps` + `ParamSpec`/`TypeVar` 同时保住运行时元数据与静态签名，测试已验证 `__name__`/`__doc__`。
   - 注释解释"为什么"（退避设计意图、裸 raise 保 traceback、不可达行为类型检查器而留），而非复述代码；公开接口 docstring 覆盖参数/返回/异常。
   - 测试只依赖公开接口、按行为分 6 个测试类，多异常场景用 `parametrize` 去重；`monkeypatch` 补丁在 teardown 自动还原，无测试间污染。唯一可留意点：`monkeypatch.setattr("retry.time.sleep", ...)` 实际补丁的是共享全局 `time` 模块的属性，但 monkeypatch 会自动恢复且测试期间无其他代码调用 sleep，风险为零，无需改动。

4. **兼容性**：仅依赖标准库，要求 Python 3.10+(`typing.ParamSpec`)，已在模块 docstring 中显式声明；被测代码零第三方依赖，pytest 仅为测试框架。

**改动汇总：无功能性修改**——语法复核双文件通过、14/14 用例复跑通过、逻辑/边界/风格审查未发现缺陷，两个文件按原样作为最终版本交付。