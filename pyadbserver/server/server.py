import asyncio
import logging
from typing import Optional

from .routing import App
from .session import SmartSocketSession

logger = logging.getLogger(__name__)


class AdbServer:
    """Asyncio-based ADB smart-socket server.

    Listens on a TCP port, accepts multiple connections, and delegates each to
    a `SmartSocketSession`. Supports graceful shutdown via `host:kill`.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 5037,
        *,
        app: App,
    ) -> None:
        self._host = host
        self._port = port
        self._server: Optional[asyncio.AbstractServer] = None
        self._stopping: Optional[asyncio.Event] = None
        self._app = app
        self._app.register(app)

    @property
    def is_running(self) -> bool:
        return self._server is not None and getattr(self._server, "sockets", None) is not None

    @property
    def bound_port(self) -> Optional[int]:
        sockets = getattr(self._server, "sockets", None) if self._server else None
        if sockets:
            return sockets[0].getsockname()[1]
        return None

    async def start(self) -> None:
        if self._server is not None:
            return

        # Create the event in the running event loop
        if self._stopping is None:
            self._stopping = asyncio.Event()

        self._server = await asyncio.start_server(
            self._handle_client, self._host, self._port
        )

    async def serve_forever(self) -> None:
        if self._server is None:
            await self.start()

        assert self._server is not None
        assert self._stopping is not None
        async with self._server:
            await self._stopping.wait()

    async def stop(self) -> None:
        if self._stopping is not None:
            self._stopping.set()
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
        self._server = None

    def request_shutdown(self) -> None:
        """
        Signal the server to shutdown soon.

        It is safe to call multiple times.
        """
        if self._stopping is not None:
            self._stopping.set()
        # If we're not in serve_forever context, also proactively stop the server
        if self._server is not None:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.stop())
            except RuntimeError:
                # No running loop; best effort fallback
                pass

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        logger.debug(f"Connected")
        session = SmartSocketSession(
            reader=reader,
            writer=writer,
            app=self._app,
        )
        try:
            await session.run()
        finally:
            try:
                logger.debug(f"Disconnected")
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass


