"""Request-local cooperative cancellation without a required async dependency."""
from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_checkpoint: ContextVar[Callable[[], None] | None] = ContextVar("billfit_cancellation", default=None)


@contextmanager
def cancellation_scope(check: Callable[[], None]) -> Iterator[None]:
    """Bind the caller's cancellation check until all owned work has unwound."""
    token = _checkpoint.set(check)
    try:
        yield
    finally:
        _checkpoint.reset(token)


def check_cancelled() -> None:
    check = _checkpoint.get()
    if check is not None:
        check()
