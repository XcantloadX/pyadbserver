import asyncio
import logging
from typing import overload, Optional, TYPE_CHECKING
from dataclasses import dataclass

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
        # adb server uses short TCP connection
        # so no need to loop here
        try:
            length_hex = await self._read(4)
        except asyncio.IncompleteReadError:
            await self._send_fail(b"truncated length prefix")
            return

        try:
            payload_length = int(length_hex.decode("ascii"), 16)
        except Exception:
            await self._send_fail(b"bad length prefix")
            return

        if payload_length <= 0:
            await self._send_fail(b"empty payload")
            return

        try:
            payload = await self._read(payload_length)
        except asyncio.IncompleteReadError:
            await self._send_fail(b"truncated payload")
            return

        await self._app.dispatch(payload.decode("utf-8", errors="replace"), self)

    # Response helpers

    @overload
    async def send_okay(self) -> None: ...
    @overload
    async def send_okay(self, data: bytes) -> None: ...

    async def send_okay(self, data: Optional[bytes] = None) -> None:
        if data is not None:
            self._write(b"OKAY")
            self._write(f"{len(data):04x}".encode("ascii"))
            self._write(data)
            await self._flush()
        else:
            self._write(b"OKAY")
            await self._flush()

    async def _send_fail(self, reason: bytes) -> None:
        self._write(b"FAIL")
        self._write(f"{len(reason):04x}".encode("ascii"))
        self._write(reason)
        await self._flush()

    async def _read(self, length: int) -> bytes:
        data = await self._reader.readexactly(length)
        logger.debug(f"Recv: {data!r}")
        return data

    def _write(self, data: bytes) -> None:
        self._writer.write(data)
        logger.debug(f"Send: {data!r}")

    async def _flush(self) -> None:
        await self._writer.drain()
        logger.debug(f"Flush")
