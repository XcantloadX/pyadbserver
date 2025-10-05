import asyncio
import contextlib
import socket
import unittest

from pyadbserver.server import AdbServer


async def adb_smart_socket_request(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, payload: str) -> bytes:
    payload_bytes = payload.encode("utf-8")
    writer.write(f"{len(payload_bytes):04x}".encode("ascii"))
    writer.write(payload_bytes)
    await writer.drain()

    # Read status (OKAY/FAIL)
    status = await reader.readexactly(4)
    if status == b"OKAY":
        # May or may not have a length-prefixed body
        # Try to read next 4 bytes without blocking forever
        # We set a short timeout read; if fails, assume no body
        try:
            length_hex = await asyncio.wait_for(reader.readexactly(4), timeout=0.05)
        except Exception:
            return b""
        size = int(length_hex.decode("ascii"), 16)
        if size > 0:
            body = await reader.readexactly(size)
            return body
        return b""
    else:
        length_hex = await reader.readexactly(4)
        size = int(length_hex.decode("ascii"), 16)
        body = await reader.readexactly(size)
        return status + length_hex + body


class TestM0(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        # Bind to an ephemeral port to avoid conflicts
        self.server = AdbServer(host="127.0.0.1", port=0)
        await self.server.start()
        self.port = self.server.bound_port
        self._tasks: list[asyncio.Task] = []

    async def asyncTearDown(self) -> None:
        await self.server.stop()
        # ensure no pending tasks
        for t in self._tasks:
            with contextlib.suppress(Exception):
                t.cancel()

    async def _open_client(self):
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        return reader, writer

    async def test_host_version(self):
        reader, writer = await self._open_client()
        async with self._closing(writer):
            body = await adb_smart_socket_request(reader, writer, "host:version")
            # Expect ASCII number, default "41"
            self.assertTrue(body.decode("ascii").isdigit())

    async def test_host_kill(self):
        reader, writer = await self._open_client()
        async with self._closing(writer):
            # Send kill; server should respond OKAY and then stop
            body = await adb_smart_socket_request(reader, writer, "host:kill")
            self.assertEqual(body, b"")

        # Give the server loop a moment to handle shutdown event
        await asyncio.sleep(0.05)
        # Subsequent connections should fail since server is stopping/closed
        with self.assertRaises(Exception):
            await asyncio.open_connection("127.0.0.1", self.port)

    @contextlib.asynccontextmanager
    async def _closing(self, writer):
        try:
            yield
        finally:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()


if __name__ == "__main__":
    unittest.main()


