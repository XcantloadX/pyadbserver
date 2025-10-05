import asyncio
import logging
from typing import overload, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class SessionState:
    selected_device_id: Optional[str] = None


class SmartSocketSession:
    """One TCP client connection handling ADB smart-socket framed requests."""

    def __init__(self, *, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, host_services, device_manager) -> None:
        self._reader = reader
        self._writer = writer
        self._host_services = host_services
        self._device_manager = device_manager
        self._state = SessionState()

        # In single-device mode, preselect the only device if present
        selected = self._device_manager.get_selected("session")
        if selected is None:
            try:
                self._device_manager.select_device("session", serial=None)
            except Exception:
                # No device available yet; keep None
                pass

    async def run(self) -> None:
        # adb server 采用短连接，每次请求结束后必须立即关闭连接，不可以循环处理请求
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

        # Route
        if payload.startswith(b"host:"):
            await self._host_services.handle(payload.decode("utf-8", errors="replace"), self)
        else:
            await self._send_fail(b"unsupported service")

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
