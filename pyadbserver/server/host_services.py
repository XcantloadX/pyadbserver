from typing import Optional, Callable, TYPE_CHECKING

from .. import DEFAULT_SERVER_VERSION
if TYPE_CHECKING:
    from .session import SmartSocketSession


class HostServices:
    """Implements a subset of standard ADB host services.

    Supported:
      - host:version -> OKAY + <len><ascii-version>
      - host:kill    -> OKAY, request server shutdown, close connection
    """

    def __init__(self, *, version_provider: Optional[Callable[[], int]] = None, request_shutdown: Optional[Callable[[], None]] = None) -> None:
        self._version_provider = version_provider or (lambda: DEFAULT_SERVER_VERSION)
        self._request_shutdown = request_shutdown or (lambda: None)

    async def handle(self, payload: str, session: 'SmartSocketSession') -> bool:
        """Handle a host:* request.

        Returns True if the session should close the connection after handling.
        """
        cmd = payload[len("host:") :]
        if cmd == "version":
            version_bytes = self._version_provider()
            await session.send_okay(f'{version_bytes:04x}'.encode("ascii"))
            return False

        if cmd == "kill":
            await session.send_okay()
            # Request server shutdown and close this session
            self._request_shutdown()
            return True

        # Unknown host service
        await session._send_fail(b"unknown host service")
        return False


