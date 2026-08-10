修正后的 `retry.py` 与 `test_retry.py` 均通过语法检查。以下为最终交付的 `solution.md` 完整内容：

````markdown
# retry 装饰器 — 代码评审与最终版本

## 一、语法检查结论

| 文件 | 检查方式 | 结果 |
|---|---|---|
| `generated/retry.py`(原稿) | `ast` 静态解析 | ✅ 通过 |
| `generated/tests/test_retry.py`(原稿) | `ast` 静态解析 | ✅ 通过 |
| `generated/conftest.py` | `ast` 静态解析 | ✅ 通过(纯注释占位,无需修改) |
| `generated/retry.py`(修正后) | `ast` 静态解析 | ✅ 通过 |
| `generated/tests/test_retry.py`(修正后) | `ast` 静态解析 | ✅ 通过 |

原稿三个文件均无语法错误;评审中发现的问题全部属于**健壮性与测试完整性**层面,已在下文修正。

## 二、评审发现的问题与修正

1. **`retry_exceptions` 缺乏校验(健壮性,主要问题)**。`except retry_exceptions` 只有在异常实际发生时才会被求值。若调用方传入 `(ValueError, 42)` 之类的非法元组,装饰器定义时不报错,直到被装饰函数第一次抛出异常时才以一条指不出根因的运行期 `TypeError`("catching classes that do not inherit from BaseException is not allowed")失败,违背本模块"失败尽早暴露"的设计原则。**修正**:在定义阶段追加 `isinstance` 校验(必须是元组、且每个元素都是 `BaseException` 的子类),非法时立即 `raise TypeError`,错误信息带参数名与取值;同步更新 docstring 的"异常"小节。
2. **`wrapper` 控制流存在隐式返回 `None` 的死角(可维护性)**。原实现中,若 `max_attempts` 校验被绕过(如调用方事后修改闭包变量),`for` 循环会正常结束,函数隐式返回 `None` 并把异常吞掉。当前参数校验下此路径不可达,但显式兜底能让类型检查器确认函数不会隐式返回 `None`,也防止未来改动引入静默吞异常的回归。**修正**:循环末尾追加 `raise AssertionError("unreachable")  # pragma: no cover`,并注明为什么不可达。
3. **测试遗漏与断言盲区(测试完整性)**:
   - `test_success_after_retries` 与 `test_retry_exhausted_raises_original_exception` 虽然注入了 `sleep_log` fixture,却从未断言它,`base_delay=0` 时是否仍按规则调用 `sleep(0)`(重试间隔公式 `base_delay * backoff**attempt` 在 `base_delay=0` 时应退化为 0 而非跳过)完全未被覆盖。**修正**:分别补充 `assert sleep_log == [0, 0]`,同时验证 sleep 次数 = 实际重试次数(成功前 2 次 / 耗尽前 `max_attempts - 1` 次)。
   - 针对修正 1 新增的校验逻辑,**补充** `test_invalid_retry_exceptions_raise_type_error_at_definition`,用 `parametrize` 覆盖混入非异常类、元素非异常类(如 `int`)、列表而非元组、字符串而非元组四种非法形态,并断言错误信息包含参数名。
4. **确认无问题的点**:重试循环语义(`return` 直返 / 最后一次原样 `raise` / 非白名单异常无 `except` 分支自然传播)、退避公式 `base_delay * backoff**attempt`、`functools.wraps` 元信息保留、模块级 `time.sleep` 便于 monkeypatch、`conftest.py` 利用 pytest 的 sys.path 机制,均符合方案且逻辑正确,未做改动。

修正后测试共 14 个用例(含 parametrize 展开),全部通过公开接口断言,无真实等待。

## 三、最终代码

### `generated/retry.py`

```python
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
        ValueError: max_attempts/base_delay/backoff 取值非法时,在装饰器
            定义阶段立即抛出,让错误尽早暴露,而不是等到被装饰函数第一次
            被调用时才失败。
        TypeError: retry_exceptions 不是由异常类组成的元组时,同样在
            定义阶段抛出。
        被装饰函数自身的异常:重试耗尽或异常不在白名单时原样抛出。
    """
    if max_attempts < 1:
        raise ValueError(f"max_attempts 必须 >= 1,当前取值: {max_attempts!r}")
    if base_delay < 0:
        raise ValueError(f"base_delay 必须 >= 0,当前取值: {base_delay!r}")
    if backoff < 1:
        raise ValueError(f"backoff 必须 >= 1,当前取值: {backoff!r}")
    # retry_exceptions 只在异常发生时才被求值;若不提前校验,非法取值
    # (如混入非异常类)会拖到运行期才以晦涩的 TypeError 暴露。
    if not isinstance(retry_exceptions, tuple) or not all(
        isinstance(exc, type) and issubclass(exc, BaseException)
        for exc in retry_exceptions
    ):
        raise TypeError(
            "retry_exceptions 必须是继承自 BaseException 的异常类组成的元组,"
            f"当前取值: {retry_exceptions!r}"
        )

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
            # max_attempts >= 1 时循环必然以 return 或 raise 结束,此行不可达;
            # 保留它只为让类型检查器确认 wrapper 不会隐式返回 None。
            raise AssertionError("unreachable")  # pragma: no cover

        return wrapper

    return decorator
```

### `generated/tests/test_retry.py`

```python
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
    # base_delay=0 时仍会在每次重试前调用 sleep(0),第 3 次成功前共 2 次。
    assert sleep_log == [0, 0]


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
    # 最后一次失败后不再 sleep,故 sleep 次数 = max_attempts - 1。
    assert sleep_log == [0, 0]


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


@pytest.mark.parametrize(
    "bad_exceptions",
    [
        (ValueError, 42),
        (int,),
        [ValueError],
        "ValueError",
    ],
    ids=["混入非异常类", "元素非异常类", "列表而非元组", "字符串而非元组"],
)
def test_invalid_retry_exceptions_raise_type_error_at_definition(bad_exceptions):
    """白名单非法:定义装饰器时即抛 TypeError,而不是拖到运行期。"""
    with pytest.raises(TypeError, match="retry_exceptions"):
        retry(retry_exceptions=bad_exceptions)


def test_wraps_preserves_metadata():
    """装饰后函数的 __name__/__doc__ 与原函数一致(functools.wraps)。"""

    @retry()
    def my_function():
        """示例文档字符串。"""
        return 1

    assert my_function.__name__ == "my_function"
    assert my_function.__doc__ == "示例文档字符串。"
```

### `generated/conftest.py`

```python
# 占位文件:借助 pytest「conftest.py 所在目录自动加入 sys.path」的机制,使 tests/ 中的用例可直接 import retry,无需 sys.path hack。
```

**运行方式**:在 `generated/` 目录下执行 `pytest`,共 14 个用例(含 parametrize 展开),均不依赖真实等待。
````