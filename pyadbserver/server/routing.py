from __future__ import annotations

import re
import logging
import inspect
import contextvars
from enum import Enum, auto
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple, Union, TYPE_CHECKING
import warnings

if TYPE_CHECKING:
    from .session import SmartSocketSession
    from ..transport.device import Device
    from ..transport.device_manager import DeviceService


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


@dataclass
class Route:
    pattern: str
    handler: Callable[..., Awaitable[Optional[Response]]]
    is_device_route: bool = False
    prefix_only: bool = False


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
        self._routes: List[Route] = []

    def add_route(self, pattern: str, handler: Handler, is_device_route: bool = False, prefix_only: bool = False) -> None:
        async def _handler(*args: Any, **kwargs: Any) -> Optional[Response]:
            return await _ensure_awaitable(handler(*args, **kwargs))
        self._routes.append(Route(pattern, _handler, is_device_route, prefix_only))

    def match(self, payload: str) -> Tuple[Optional[Route], Dict[str, str]]:
        # Sort routes by pattern length (descending) to match more specific patterns first
        sorted_routes = sorted(self._routes, key=lambda r: len(r.pattern), reverse=True)
        for route in sorted_routes:
            ok, params = self._match_pattern(route.pattern, payload)
            if ok:
                return route, params
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
    def __init__(self, *, device_manager: "DeviceService") -> None:
        self._router = Router()
        self._device_manager = device_manager

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

    def device_route(self, pattern: str, *, prefix_only: bool = False) -> Callable[[Handler], Handler]:
        """
        Register a handler for a given pattern that requires a device.

        :param pattern: The pattern to register the handler for.
        :param prefix_only: If True, the handler will only be called if a device is specified via "host-serial"
        :return: The decorator function.
        """
        def _decorator(func: Handler) -> Handler:
            self._router.add_route(pattern, func, is_device_route=True, prefix_only=prefix_only)
            return func
        return _decorator

    def register(self, obj: Any) -> None:
        """
        Register all methods decorated with @route decorator of an object.

        :param obj: The object to register the methods for.
        """
        for name in dir(obj):
            fn = getattr(obj, name)

            attr_source = fn
            if hasattr(attr_source, "__func__"):
                attr_source = attr_source.__func__

            pattern = getattr(attr_source, "__route_pattern__", None)
            is_device_route = getattr(attr_source, "__is_device_route__", False)
            prefix_only = getattr(attr_source, "__prefix_only__", False)

            if pattern is not None:
                self._router.add_route(pattern, fn, is_device_route=is_device_route, prefix_only=prefix_only)

    async def dispatch(self, payload: str, session: 'SmartSocketSession') -> ResponseAction:
        """
        Dispatch a payload to the appropriate handler.

        :param payload: The payload to dispatch.
        :param session: The session to dispatch the payload to.
        :return: The response action.
        """
        device: Optional["Device"] = None
        
        # host-serial:<serial>:<request>
        match = re.match(r"host-serial:([^:]+):(.+)", payload)
        if match:
            serial, payload = match.groups()
            device = self._device_manager.get_device(serial)
            if device is None:
                await session.send_fail(f"device '{serial}' not found".encode("utf-8"))
                return ResponseAction.CLOSE
        
        route, params = self._router.match(payload)
        if route is None and payload.startswith("host:"):
            # Fallback: allow routes defined without the 'host:' prefix to match
            warnings.warn(
                "Some route does not start with 'host:', falling back to match without 'host:' prefix. "
                "This will only show once. "
                "Enable logging to see more details."
            )
            logger.warning(f"Route '{payload}' does not start with 'host:', falling back to match without 'host:' prefix")
            route, params = self._router.match(payload[len("host:"):])
        if route is None:
            await session.send_fail(b"unsupported operation for payload: " + payload.encode("utf-8"))
            return ResponseAction.CLOSE

        handler = route.handler
        handler_args: List[Any] = []
        
        if route.is_device_route:
            if device is None:
                device = self._device_manager.get_selected(session.id)
            
            if device is None:
                # device_route() should select any device if not selected
                # but device_route(prefix_only=True) should fail.
                if not route.prefix_only:
                    # Try to select any device
                    devices = self._device_manager.list_devices()
                    if devices:
                        device = devices[0] # Select first one
                else:
                    await session.send_fail(b"no device specified for device-only command")
                    return ResponseAction.CLOSE
            
            if device is None:
                await session.send_fail(b"no device available")
                return ResponseAction.CLOSE
            
            handler_args.append(device)

        try:
            token = g_session.set(session)
            try:
                result = await handler(*handler_args, **params)
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
        setattr(func, "__is_device_route__", False)
        return func
    return _decorator


def device_route(pattern: str, *, prefix_only: bool = False) -> Callable[[Handler], Handler]:
    def _decorator(func: Handler) -> Handler:
        setattr(func, "__route_pattern__", pattern)
        setattr(func, "__is_device_route__", True)
        setattr(func, "__prefix_only__", prefix_only)
        return func
    return _decorator