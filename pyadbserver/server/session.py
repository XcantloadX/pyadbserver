import asyncio
import logging
from typing import overload, Optional, TYPE_CHECKING
from dataclasses import dataclass

from .routing import ResponseAction

if TYPE_CHECKING:
    from .routing import App
    from ..transport.device_manager import DeviceService

logger = logging.getLogger(__name__)

@dataclass
class SessionState:
    selected_device_id: Optional[str] = None


class SmartSocketSession:
    """One TCP client connection handling ADB smart-socket framed requests."""

    def __init__(
        self,
        *,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        app: 'App'
    ) -> None:
        self._reader = reader
        self._writer = writer
        self._app = app
        self._state = SessionState()

    async def run(self) -> None:
        # adb server uses short TCP connection by default
        # but handler can choose to keep the connection alive
        while True:
            try:
                length_hex = await self._read(4)
            except asyncio.IncompleteReadError:
                await self.send_fail(b"truncated length prefix")
                return

            try:
                payload_length = int(length_hex.decode("ascii"), 16)
            except Exception:
                await self.send_fail(b"bad length prefix")
                return

            if payload_length <= 0:
                await self.send_fail(b"empty payload")
                return

            try:
                payload = await self._read(payload_length)
            except asyncio.IncompleteReadError:
                await self.send_fail(b"truncated payload")
                return

            action = await self._app.dispatch(payload.decode("utf-8", errors="replace"), self)
            
            # close or keep-alive according to handler's response
            if action == ResponseAction.CLOSE:
                return
            elif action == ResponseAction.KEEP_ALIVE:
                continue
            else:
                raise ValueError(f"unknown response action: {action}")

    # Response helpers

    @overload
    async def send_okay(self, *, flush: bool = True, raw: bool = False) -> None: ...
    @overload
    async def send_okay(self, data: bytes, *, flush: bool = True, raw: bool = False) -> None: ...

    async def send_okay(self, data: Optional[bytes] = None, *, flush: bool = True, raw: bool = False) -> None:
        if data is not None:
            self.write(b"OKAY")
            # raw payload: do not send length prefix
            if not raw:
                self.write(f"{len(data):04x}".encode("ascii"))
            self.write(data)
            if flush:
                await self._flush()
        else:
            self.write(b"OKAY")
            if flush:
                await self._flush()

    async def send_fail(self, reason: bytes, *, flush: bool = True, raw: bool = False) -> None:
        self.write(b"FAIL")
        if not raw:
            self.write(f"{len(reason):04x}".encode("ascii"))
        self.write(reason)
        if flush:
            await self._flush()

    async def _read(self, length: int) -> bytes:
        data = await self._reader.readexactly(length)
        logger.debug(f"Recv: {data!r}")
        return data

    def write(self, data: bytes) -> None:
        """
        Write data to the underlying writer.

        Usually you should use `send_okay` or `send_fail` instead.
        """
        self._writer.write(data)
        logger.debug(f"Send: {data!r}")

    async def _flush(self) -> None:
        await self._writer.drain()
        logger.debug(f"Flush")
