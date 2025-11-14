from __future__ import annotations

import asyncio
import inspect
import sys
from pathlib import Path
from typing import Any

import pytest


def _get_event_loop(request: pytest.FixtureRequest) -> asyncio.AbstractEventLoop:
    loop = request.getfixturevalue("event_loop")
    if not isinstance(loop, asyncio.AbstractEventLoop):  # pragma: no cover - defensive
        raise TypeError("event_loop fixture must provide an asyncio event loop")
    return loop


def _resolve_kwargs(request: pytest.FixtureRequest, argnames: tuple[str, ...]) -> dict[str, Any]:
    return {name: request.getfixturevalue(name) for name in argnames}


@pytest.fixture(scope="session")
def event_loop() -> asyncio.AbstractEventLoop:
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.hookimpl(tryfirst=True)
def pytest_fixture_setup(fixturedef: pytest.FixtureDef[Any], request: pytest.FixtureRequest) -> Any:
    if inspect.iscoroutinefunction(fixturedef.func):
        loop = _get_event_loop(request)
        kwargs = _resolve_kwargs(request, fixturedef.argnames)
        result = loop.run_until_complete(fixturedef.func(**kwargs))
        fixturedef.cached_result = (result, 0, None)
        return result

    if inspect.isasyncgenfunction(fixturedef.func):
        loop = _get_event_loop(request)
        kwargs = _resolve_kwargs(request, fixturedef.argnames)
        async_gen = fixturedef.func(**kwargs)

        async def get_value() -> Any:
            try:
                value = await async_gen.__anext__()
            except StopAsyncIteration as exc:  # pragma: no cover - defensive
                raise RuntimeError("Async generator fixture didn't yield") from exc

            async def finalizer() -> None:
                try:
                    await async_gen.__anext__()
                except StopAsyncIteration:
                    return
                else:  # pragma: no cover - defensive
                    raise RuntimeError("Async generator fixture yielded more than once")

            request.addfinalizer(lambda: loop.run_until_complete(finalizer()))
            return value

        result = loop.run_until_complete(get_value())
        fixturedef.cached_result = (result, 0, None)
        return result

    return None


@pytest.hookimpl(tryfirst=True)
def pytest_pyfunc_call(pyfuncitem: pytest.Function) -> bool | None:
    test_function = pyfuncitem.obj
    if asyncio.iscoroutinefunction(test_function):
        loop = pyfuncitem._request.getfixturevalue("event_loop")  # type: ignore[attr-defined]
        kwargs = {
            name: pyfuncitem.funcargs[name]
            for name in pyfuncitem._fixtureinfo.argnames  # type: ignore[attr-defined]
        }
        loop.run_until_complete(test_function(**kwargs))
        return True
    return None


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "asyncio: mark test as requiring asyncio support")
    repo_root = Path(__file__).resolve().parents[1]
    repo_root_str = str(repo_root)
    if repo_root_str not in sys.path:
        sys.path.insert(0, repo_root_str)
