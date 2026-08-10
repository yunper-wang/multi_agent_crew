"""A retry decorator with exponential backoff and selective exception handling.

Usage::

    @retry(max_retries=3, base_delay=0.1, backoff_factor=2.0,
           exceptions=(ConnectionError,))
    def fetch_data():
        ...

The decorated function is retried at most ``max_retries`` times when it raises
one of ``exceptions``. Between attempts it sleeps for ``base_delay`` seconds,
multiplied by ``backoff_factor`` after each failed attempt. Any exception that
is not an instance of ``exceptions`` propagates immediately.
"""

from __future__ import annotations

import functools
import time
from typing import Any, Callable, Tuple, Type, TypeVar

F = TypeVar("F", bound=Callable[..., Any])

__all__ = ["retry"]


def retry(
    max_retries: int = 3,
    base_delay: float = 0.1,
    backoff_factor: float = 2.0,
    exceptions: Tuple[Type[BaseException], ...] = (Exception,),
) -> Callable[[F], F]:
    """Return a decorator that retries the wrapped function on failure.

    Args:
        max_retries: Maximum number of retries after the initial attempt
            (total attempts = ``max_retries + 1``).
        base_delay: Delay in seconds before the first retry.
        backoff_factor: Multiplier applied to the delay after each failure.
        exceptions: Tuple of exception types that trigger a retry. Any other
            exception is raised immediately without retrying.

    Returns:
        A decorator applying the retry policy to the wrapped callable.

    Raises:
        ValueError: If the configuration is invalid.
    """
    if max_retries < 0:
        raise ValueError("max_retries must be >= 0")
    if base_delay < 0:
        raise ValueError("base_delay must be >= 0")
    if backoff_factor < 1:
        raise ValueError("backoff_factor must be >= 1")
    if not exceptions:
        raise ValueError("exceptions must not be empty")

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            delay = base_delay
            attempt = 0
            while True:
                try:
                    return func(*args, **kwargs)
                except exceptions:
                    if attempt >= max_retries:
                        raise
                    time.sleep(delay)
                    delay *= backoff_factor
                    attempt += 1

        return wrapper  # type: ignore[return-value]

    return decorator
