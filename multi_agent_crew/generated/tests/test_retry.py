"""Unit tests for the ``retry`` decorator.

The tests cover:
- success on the first attempt (no retry triggered);
- success after a number of retriable failures;
- re-raising the last exception when retries are exhausted;
- immediate propagation of non-retriable exception types;
- exponential backoff intervals passed to ``time.sleep``;
- preservation of the wrapped function's metadata.
"""

import sys
import time
from pathlib import Path
from typing import Any, Dict, List

import pytest

# Make the implementation module (generated/retry.py) importable
# regardless of the directory pytest is invoked from.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from retry import retry  # noqa: E402


@pytest.fixture(name="sleep_calls")
def sleep_calls_fixture(monkeypatch: pytest.MonkeyPatch) -> List[float]:
    """Replace ``time.sleep`` with a recorder and return the recorded delays."""
    calls: List[float] = []
    monkeypatch.setattr(time, "sleep", calls.append)
    return calls


class TestRetryBehaviour:
    """Core retry semantics."""

    def test_success_on_first_attempt(self, sleep_calls: List[float]) -> None:
        counter: Dict[str, int] = {"count": 0}

        @retry(max_retries=3, base_delay=0.01, exceptions=(ValueError,))
        def func() -> str:
            counter["count"] += 1
            return "ok"

        assert func() == "ok"
        assert counter["count"] == 1
        assert sleep_calls == []

    def test_success_after_retriable_failures(self, sleep_calls: List[float]) -> None:
        counter: Dict[str, int] = {"count": 0}

        @retry(max_retries=3, base_delay=0.01, exceptions=(ValueError,))
        def flaky() -> str:
            counter["count"] += 1
            if counter["count"] < 3:
                raise ValueError("temporary failure")
            return "done"

        assert flaky() == "done"
        assert counter["count"] == 3
        assert len(sleep_calls) == 2

    def test_raises_last_exception_after_max_retries(
        self, sleep_calls: List[float]
    ) -> None:
        counter: Dict[str, int] = {"count": 0}

        @retry(max_retries=2, base_delay=0.01, exceptions=(ValueError,))
        def always_fail() -> None:
            counter["count"] += 1
            raise ValueError("permanent failure")

        with pytest.raises(ValueError, match="permanent failure"):
            always_fail()

        # 1 initial attempt + 2 retries.
        assert counter["count"] == 3
        assert len(sleep_calls) == 2

    def test_max_retries_zero_means_single_attempt(
        self, sleep_calls: List[float]
    ) -> None:
        counter: Dict[str, int] = {"count": 0}

        @retry(max_retries=0, base_delay=0.01, exceptions=(ValueError,))
        def func() -> None:
            counter["count"] += 1
            raise ValueError("no retry expected")

        with pytest.raises(ValueError, match="no retry expected"):
            func()

        assert counter["count"] == 1
        assert sleep_calls == []


class TestExceptionFiltering:
    """Only the specified exception types should trigger a retry."""

    def test_non_matching_exception_propagates_immediately(
        self, sleep_calls: List[float]
    ) -> None:
        counter: Dict[str, int] = {"count": 0}

        @retry(max_retries=5, base_delay=0.01, exceptions=(ValueError,))
        def func() -> None:
            counter["count"] += 1
            raise TypeError("not retriable")

        with pytest.raises(TypeError, match="not retriable"):
            func()

        assert counter["count"] == 1
        assert sleep_calls == []

    def test_multiple_exception_types_are_retriable(
        self, sleep_calls: List[float]
    ) -> None:
        counter: Dict[str, int] = {"count": 0}

        @retry(max_retries=3, base_delay=0.01, exceptions=(ValueError, KeyError))
        def flaky() -> str:
            counter["count"] += 1
            if counter["count"] == 1:
                raise ValueError("first")
            if counter["count"] == 2:
                raise KeyError("second")
            return "ok"

        assert flaky() == "ok"
        assert counter["count"] == 3
        assert len(sleep_calls) == 2

    def test_exception_subclass_is_retriable(self, sleep_calls: List[float]) -> None:
        counter: Dict[str, int] = {"count": 0}

        @retry(max_retries=2, base_delay=0.01, exceptions=(Exception,))
        def flaky() -> str:
            counter["count"] += 1
            if counter["count"] == 1:
                raise ValueError("subclass of Exception")
            return "ok"

        assert flaky() == "ok"
        assert counter["count"] == 2

    def test_default_exceptions_is_exception(self, sleep_calls: List[float]) -> None:
        counter: Dict[str, int] = {"count": 0}

        @retry(max_retries=2, base_delay=0.01)
        def flaky() -> str:
            counter["count"] += 1
            if counter["count"] == 1:
                raise RuntimeError("generic error")
            return "ok"

        assert flaky() == "ok"
        assert counter["count"] == 2


class TestExponentialBackoff:
    """The delay between attempts must grow exponentially."""

    @pytest.mark.parametrize(
        ("base_delay", "backoff_factor", "expected"),
        [
            (1.0, 2.0, [1.0, 2.0, 4.0]),
            (0.5, 3.0, [0.5, 1.5, 4.5]),
            (0.1, 2.0, [0.1, 0.2, 0.4]),
        ],
    )
    def test_backoff_intervals(
        self,
        sleep_calls: List[float],
        base_delay: float,
        backoff_factor: float,
        expected: List[float],
    ) -> None:
        counter: Dict[str, int] = {"count": 0}

        @retry(
            max_retries=3,
            base_delay=base_delay,
            backoff_factor=backoff_factor,
            exceptions=(RuntimeError,),
        )
        def flaky() -> str:
            counter["count"] += 1
            if counter["count"] <= 3:
                raise RuntimeError("boom")
            return "ok"

        assert flaky() == "ok"
        assert counter["count"] == 4
        assert sleep_calls == pytest.approx(expected)

    def test_no_sleep_after_final_attempt(self, sleep_calls: List[float]) -> None:
        @retry(max_retries=2, base_delay=1.0, backoff_factor=2.0, exceptions=(ValueError,))
        def always_fail() -> None:
            raise ValueError("boom")

        with pytest.raises(ValueError):
            always_fail()

        # Sleeps happen only *between* attempts: 3 attempts -> 2 sleeps.
        assert sleep_calls == pytest.approx([1.0, 2.0])


class TestDecoratorProperties:
    """The decorator must behave like a well-mannered wrapper."""

    def test_preserves_function_metadata(self) -> None:
        @retry()
        def sample() -> int:
            """Sample docstring."""
            return 42

        assert sample.__name__ == "sample"
        assert sample.__doc__ == "Sample docstring."
        assert sample() == 42

    def test_passes_through_args_and_kwargs(self, sleep_calls: List[float]) -> None:
        @retry(max_retries=1, base_delay=0.01, exceptions=(ValueError,))
        def add(a: int, b: int = 0) -> int:
            return a + b

        assert add(2, b=3) == 5

    @pytest.mark.parametrize(
        ("kwargs", "match"),
        [
            ({"max_retries": -1}, "max_retries"),
            ({"base_delay": -0.1}, "base_delay"),
            ({"backoff_factor": 0.5}, "backoff_factor"),
            ({"exceptions": ()}, "exceptions"),
        ],
    )
    def test_invalid_configuration_raises(
        self, kwargs: Dict[str, Any], match: str
    ) -> None:
        with pytest.raises(ValueError, match=match):
            retry(**kwargs)
