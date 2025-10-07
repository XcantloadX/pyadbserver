import os
import logging
import signal
import asyncio
import argparse
import contextlib


from .server import AdbServer
from .server.routing import App
from .services.host import HostService
from .services import LocalShellService
from .transport.device_manager import SingleDeviceService
from .transport.device import Device
from .services import SyncV1Service, ForwardService, MemoryFileSystem

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="pyadbserver - minimal ADB smart-socket server")
    parser.add_argument("--host", default="127.0.0.1", help="listen host (default: 127.0.0.1)")
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("ADB_SERVER_PORT", "5037")),
        help="listen port (default: $ADB_SERVER_PORT or 5037)",
    )
    return parser.parse_args()


async def _run_server(host: str, port: int) -> None:
    device_manager = SingleDeviceService(device=Device(
        id="device-1",
        serial="fake-5554",
        state="device",
        properties={
            "product": "pyadbserver_product",
            "model": "pyadbserver_model",
            "device": "pyadbserver_device",
            "transport_id": "1",
        },
    ))
    app = App(device_manager=device_manager)
    server = AdbServer(host=host, port=port, app=app)
    app.register(HostService(server, device_manager))
    app.register(LocalShellService())
    app.register(SyncV1Service(MemoryFileSystem(auto_create=True)))
    app.register(ForwardService())
    await server.start()
    logger.info(f"pyadbserver listening on {host}:{server.bound_port}")

    stop_event = asyncio.Event()

    def _handle_signal(*_):
        stop_event.set()

    try:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            with contextlib.suppress(NotImplementedError):
                loop.add_signal_handler(sig, _handle_signal)
    except RuntimeError:
        pass

    try:
        await asyncio.wait(
            [asyncio.create_task(server.serve_forever()), asyncio.create_task(stop_event.wait())],
            return_when=asyncio.FIRST_COMPLETED,
        )
    finally:
        await server.stop()


def main() -> None:
    logging.basicConfig(level=logging.DEBUG, format='[%(asctime)s][%(levelname)s] %(message)s')
    args = parse_args()
    asyncio.run(_run_server(args.host, args.port))


if __name__ == "__main__":
    main()


