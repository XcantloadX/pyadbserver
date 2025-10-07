from __future__ import annotations

import re
import logging
import inspect
import contextvars
from enum import Enum, auto
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple, Union, TYPE_CHECKING

if TYPE_CHECKING:
    from .session import SmartSocketSession

class ResponseAction(Enum):
    CLOSE = auto()
    KEEP_ALIVE = auto()


@dataclass
class Response:
    kind: str
    data: Optional[bytes] = None
    action: ResponseAction = ResponseAction.CLOSE
    raw: bool = False

logger = logging.getLogger(__name__)
g_session: contextvars.ContextVar["SmartSocketSession"] = contextvars.ContextVar("current_session")
Handler = Callable[..., Union[Awaitable[Response], Response, None]]

def OK(data: Optional[bytes] = None, raw: bool = False, action: ResponseAction = ResponseAction.CLOSE) -> Response:
    """
    Sends an OK response with optional data.
    """
    return Response("OK", data, action, raw)


def FAIL(reason: Union[str, bytes], action: ResponseAction = ResponseAction.CLOSE, raw: bool = False) -> Response:
    """
    Sends a FAIL response with an optional reason.
    """
    return Response("FAIL", reason.encode("utf-8") if isinstance(reason, str) else reason, action, raw)


def NOOP(action: ResponseAction = ResponseAction.CLOSE, raw: bool = False) -> Response:
    """
    Sends nothing.

    This is useful when you need a custom response that does not follow the OK/FAIL pattern.
    """
    return Response("NOOP", None, action, raw)

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
        # Sort routes by pattern length (descending) to match more specific patterns first
        sorted_routes = sorted(self._routes, key=lambda r: len(r[0]), reverse=True)
        for pattern, handler in sorted_routes:
            ok, params = self._match_pattern(pattern, payload)
            if ok:
                return handler, params
        return None, {}

    @staticmethod
    def _match_pattern(pattern: str, payload: str) -> Tuple[bool, Dict[str, str]]:
        # Advanced pattern matching with support for <name> placeholders and literal characters
        # Convert pattern to regex: <name> becomes (?P<name>...) and escape literal chars
        regex_parts = []
        params_order = []
        i = 0
        while i < len(pattern):
            if pattern[i] == '<':
                # Find the closing >
                close_idx = pattern.find('>', i)
                if close_idx == -1:
                    # Malformed pattern
                    return False, {}
                param_name = pattern[i+1:close_idx]
                params_order.append(param_name)
                
                # Determine what comes after this placeholder to decide the capture pattern
                next_literal = ''
                if close_idx + 1 < len(pattern):
                    # Find the next placeholder or end of string
                    next_open = pattern.find('<', close_idx + 1)
                    if next_open == -1:
                        # No more placeholders, use the rest as literal
                        next_literal = pattern[close_idx + 1:]
                    else:
                        # Use characters between this > and next < as literal
                        next_literal = pattern[close_idx + 1:next_open]
                
                if next_literal:
                    # Capture until the next literal character(s)
                    # Escape the literal for use in regex
                    escaped_literal = re.escape(next_literal)
                    regex_parts.append(f"(?P<{param_name}>[^{re.escape(next_literal[0])}]+)")
                else:
                    # Last parameter, capture everything remaining
                    regex_parts.append(f"(?P<{param_name}>.+)")
                
                i = close_idx + 1
            else:
                # Find the next placeholder or end of string
                next_open = pattern.find('<', i)
                if next_open == -1:
                    # No more placeholders, rest is literal
                    literal = pattern[i:]
                    regex_parts.append(re.escape(literal))
                    i = len(pattern)
                else:
                    # Literal characters before next placeholder
                    literal = pattern[i:next_open]
                    regex_parts.append(re.escape(literal))
                    i = next_open
        
        # Construct the full regex
        regex_pattern = '^' + ''.join(regex_parts) + '$'
        
        # Try to match
        match = re.match(regex_pattern, payload)
        if not match:
            return False, {}
        
        # Extract parameters
        params = match.groupdict()
        return True, params


class App:
    def __init__(self) -> None:
        self._router = Router()

    # decorator sugar
    def route(self, pattern: str) -> Callable[[Handler], Handler]:
        """
        Register a handler for a given pattern.

        :param pattern: The pattern to register the handler for.
        :return: The decorator function.
        """
        def _decorator(func: Handler) -> Handler:
            self._router.add_route(pattern, func)
            return func
        return _decorator

    def register(self, obj: Any) -> None:
        """
        Register all methods decorated with @route decorator of an object.

        :param obj: The object to register the methods for.
        """
        for name in dir(obj):
            fn = getattr(obj, name)
            pattern = getattr(fn, "__route_pattern__", None)
            if pattern is None and hasattr(fn, "__func__"):
                # bound method -> check underlying function
                pattern = getattr(getattr(fn, "__func__"), "__route_pattern__", None)
            if pattern is not None:
                self._router.add_route(pattern, fn)

    async def dispatch(self, payload: str, session: 'SmartSocketSession') -> ResponseAction:
        """
        Dispatch a payload to the appropriate handler.

        :param payload: The payload to dispatch.
        :param session: The session to dispatch the payload to.
        :return: The response action.
        """
        handler, params = self._router.match(payload)
        if handler is None:
            await session.send_fail(b"unsupported operation")
            return ResponseAction.CLOSE

        try:
            token = g_session.set(session)
            try:
                result = await handler(**params)
            finally:
                g_session.reset(token)
        except Exception:
            logger.exception("Error when dispatching payload %s", payload)
            await session.send_fail(b"internal error")
            return ResponseAction.CLOSE

        if result is None:
            # default to OK without body
            await session.send_okay()
            return ResponseAction.CLOSE
        if result.kind == "OK":
            await session.send_okay(data=result.data or b"", raw=result.raw)
        elif result.kind == "FAIL":
            await session.send_fail(result.data or b"unknown error", raw=result.raw)
        elif result.kind == "NOOP":
            pass
        else:
            raise ValueError(f"unknown response kind: {result.kind}")
        
        return result.action


def route(pattern: str) -> Callable[[Handler], Handler]:
    def _decorator(func: Handler) -> Handler:
        setattr(func, "__route_pattern__", pattern)
        return func
    return _decorator