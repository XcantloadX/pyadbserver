from __future__ import annotations

import inspect
import contextvars
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple, Union, TYPE_CHECKING

if TYPE_CHECKING:
    from .session import SmartSocketSession

# global magic session context
g_session: contextvars.ContextVar["SmartSocketSession"] = contextvars.ContextVar("current_session")


# Response primitives -------------------------------------------------------

@dataclass
class Response:
    kind: str
    data: Optional[bytes] = None


def OK(data: Optional[bytes] = None) -> Response:
    return Response("OK", data)


def FAIL(reason: Union[str, bytes]) -> Response:
    return Response("FAIL", reason.encode("utf-8") if isinstance(reason, str) else reason)


# Route registration --------------------------------------------------------

Handler = Callable[..., Union[Awaitable[Response], Response, None]]


def _ensure_awaitable(result: Union[Response, None, Awaitable[Response]]) -> Awaitable[Optional[Response]]:
    if inspect.isawaitable(result):
        return result  # type: ignore[return-value]
    async def _wrapped() -> Optional[Response]:
        return result  # type: ignore[misc]
    return _wrapped()


class Router:
    def __init__(self) -> None:
        self._routes: List[Tuple[str, Callable[..., Awaitable[Optional[Response]]]]] = []

    def add_route(self, pattern: str, handler: Handler) -> None:
        async def _handler(*args: Any, **kwargs: Any) -> Optional[Response]:
            return await _ensure_awaitable(handler(*args, **kwargs))
        self._routes.append((pattern, _handler))

    def match(self, payload: str) -> Tuple[Optional[Callable[..., Awaitable[Optional[Response]]]], Dict[str, str]]:
        for pattern, handler in self._routes:
            ok, params = self._match_pattern(pattern, payload)
            if ok:
                return handler, params
        return None, {}

    @staticmethod
    def _match_pattern(pattern: str, payload: str) -> Tuple[bool, Dict[str, str]]:
        # simple pattern matching by colon, support <name> placeholder
        p_segs = pattern.split(":")
        s_segs = payload.split(":")
        if len(p_segs) != len(s_segs):
            return False, {}
        params: Dict[str, str] = {}
        for p, s in zip(p_segs, s_segs):
            if p.startswith("<") and p.endswith(">"):
                params[p[1:-1]] = s
            elif p != s:
                return False, {}
        return True, params


class App:
    def __init__(self) -> None:
        self._router = Router()

    # decorator sugar
    def route(self, pattern: str) -> Callable[[Handler], Handler]:
        def _decorator(func: Handler) -> Handler:
            self._router.add_route(pattern, func)
            return func
        return _decorator

    def register(self, obj: Any) -> None:
        # register instance methods with @route decorator
        for name in dir(obj):
            fn = getattr(obj, name)
            pattern = getattr(fn, "__route_pattern__", None)
            if pattern is None and hasattr(fn, "__func__"):
                # bound method -> check underlying function
                pattern = getattr(getattr(fn, "__func__"), "__route_pattern__", None)
            if pattern is not None:
                self._router.add_route(pattern, fn)

    async def dispatch(self, payload: str, session: 'SmartSocketSession') -> None:
        handler, params = self._router.match(payload)
        if handler is None:
            await session._send_fail(b"unknown host service")
            return

        try:
            token = g_session.set(session)
            try:
                result = await handler(**params)
            finally:
                g_session.reset(token)
        except Exception:
            await session._send_fail(b"internal error")
            return

        if result is None:
            # default to OK without body
            await session.send_okay()
            return
        if result.kind == "OK":
            await session.send_okay(result.data or b"")
        else:
            await session._send_fail(result.data or b"unknown error")


# Method decorator usable before App exists ---------------------------------

def route(pattern: str) -> Callable[[Handler], Handler]:
    def _decorator(func: Handler) -> Handler:
        setattr(func, "__route_pattern__", pattern)
        return func
    return _decorator


