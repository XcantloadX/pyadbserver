from __future__ import annotations

import asyncio
import io
import struct
from typing import TYPE_CHECKING
import logging

from ..server.routing import device_route, route, NOOP, ResponseAction, g_session
from ..transport.device import Device
from .fs import AbstractFileSystem, LocalFileSystem, FileStat, Dirent

if TYPE_CHECKING:
    from ..server.session import SmartSocketSession

logger = logging.getLogger(__name__)

# ==== sync v1 constants (align to file_sync_protocol.h) ====
ID_LIST = b"LIST"
ID_STAT = b"STAT"
ID_RECV = b"RECV"
ID_SEND = b"SEND"
ID_DENT = b"DENT"
ID_DATA = b"DATA"
ID_DONE = b"DONE"
ID_OKAY = b"OKAY"
ID_FAIL = b"FAIL"
ID_QUIT = b"QUIT"

UINT32 = struct.Struct("<I")


async def _read_exact(session: 'SmartSocketSession', length: int) -> bytes:
    return await session._read(length)


def _pack_request(id4: bytes, value: int) -> bytes:
    return id4 + UINT32.pack(value)


class SyncV1Service:
    """ADB Sync v1 服务实现（LIST/STAT/RECV/SEND/QUIT）。

    首版：仅 v1，未实现 v2/压缩。
    文件系统通过 AbstractFileSystem 注入，默认使用 LocalFileSystem(当前目录)。
    """

    def __init__(self, fs: AbstractFileSystem) -> None:
        self._fs = fs

    @device_route("sync:")
    async def sync_entry(self, device: "Device"):
        session = g_session.get()
        # Accept and enter sync loop
        await session.send_okay(flush=True)
        await self._serve_sync_loop(session)
        return NOOP(action=ResponseAction.CLOSE)

    async def _serve_sync_loop(self, session: 'SmartSocketSession') -> None:
        while True:
            try:
                header = await _read_exact(session, 8)
            except asyncio.IncompleteReadError:
                return
            if len(header) < 8:
                return
            cmd = header[:4]
            length = UINT32.unpack_from(header, 4)[0]

            if cmd == ID_QUIT:
                return

            try:
                if cmd in (ID_LIST, ID_STAT, ID_RECV, ID_SEND):
                    path = b""
                    if length > 0:
                        path = await _read_exact(session, length)
                    # path 为 utf-8（不含终止符）
                    path_str = path.decode('utf-8', errors='replace')

                    if cmd == ID_LIST:
                        await self._handle_list(session, path_str)
                        return
                    elif cmd == ID_STAT:
                        await self._handle_stat(session, path_str)
                    elif cmd == ID_RECV:
                        await self._handle_recv(session, path_str)
                    elif cmd == ID_SEND:
                        await self._handle_send(session, path_str)
                else:
                    await self._send_fail(session, b"unknown sync id")
                    return
            except Exception as e:
                await self._send_fail(session, str(e).encode('utf-8', errors='replace'))
                return

    async def _handle_list(self, session: 'SmartSocketSession', path: str) -> None:
        for dent in self._fs.iterdir(path):
            payload = struct.pack(
                "<4sIIII",
                ID_DENT,
                dent.mode,
                dent.size,
                dent.mtime,
                len(dent.name.encode('utf-8')),
            ) + dent.name.encode('utf-8')
            session.write(payload)
            await session._flush()
        session.write(_pack_request(ID_DONE, 0))
        await session._flush()

    async def _handle_stat(self, session: 'SmartSocketSession', path: str) -> None:
        try:
            st = self._fs.stat(path)
        except FileNotFoundError:
            st = FileStat(mode=0, size=0, mtime=0)
        payload = struct.pack("<4sIII", ID_STAT, st.mode, st.size, st.mtime)
        session.write(payload)
        await session._flush()

    async def _handle_recv(self, session: 'SmartSocketSession', path: str) -> None:
        with self._fs.open_for_read(path) as f:
            with session.suppress_log():
                logger.debug(f"Start RECV {path}")
                while True:
                    chunk = f.read(64 * 1024)
                    if not chunk:
                        break
                    session.write(_pack_request(ID_DATA, len(chunk)))
                    session.write(chunk)
                    await session._flush()
        session.write(_pack_request(ID_DONE, 0))
        await session._flush()

    async def _handle_send(self, session: 'SmartSocketSession', spec: str) -> None:
        # spec: "path,mode"
        comma = spec.rfind(',')
        if comma == -1:
            await self._send_fail(session, b"bad SEND spec")
            return
        path = spec[:comma]
        try:
            mode = int(spec[comma + 1:], 10)
        except ValueError:
            await self._send_fail(session, b"bad mode")
            return

        f = self._fs.open_for_write(path, mode)
        try:
            mtime: int | None = None
            logger.debug(f"Start SEND {path}")
            while True:
                with session.suppress_log():
                    header = await _read_exact(session, 8)
                    cmd = header[:4]
                    length = UINT32.unpack_from(header, 4)[0]
                    if cmd == ID_DATA:
                        if length > 0:
                            data = await _read_exact(session, length)
                            f.write(data)
                    elif cmd == ID_DONE:
                        mtime = length
                        break
                    else:
                        await self._send_fail(session, b"unexpected chunk in SEND")
                        return
        finally:
            f.close()

        if mtime is not None:
            try:
                self._fs.set_mtime(path, mtime)
            except Exception:
                pass

        session.write(_pack_request(ID_OKAY, 0))
        await session._flush()

    async def _send_fail(self, session: 'SmartSocketSession', message: bytes) -> None:
        session.write(_pack_request(ID_FAIL, len(message)))
        if message:
            session.write(message)
        await session._flush()


