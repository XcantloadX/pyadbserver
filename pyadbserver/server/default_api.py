from typing import TYPE_CHECKING

from .. import DEFAULT_SERVER_VERSION
from .routing import route, OK
if TYPE_CHECKING:
    from .adb_server import AdbServer
    from ..transport.device_manager import DeviceService


class DefaultAPI:
    def __init__(self, server: 'AdbServer', device_manager: 'DeviceService') -> None:
        self._adb_server = server
        self._device_manager = device_manager

    @route("host:version")
    async def version(self):
        return OK(f"{DEFAULT_SERVER_VERSION:04x}".encode("ascii"))

    @route("host:kill")
    async def kill(self):
        self._adb_server.request_shutdown()
        return OK()

    @route("host:devices")
    async def devices(self):
        devices = self._device_manager.list_devices()
        lines = [f"{d.serial}\t{d.state}" for d in devices]
        response = "\n".join(lines)
        if response:
            response += "\n"
        return OK(response.encode("utf-8"))

    @route("host:devices-l")
    async def devices_l(self):
        devices = self._device_manager.list_devices()
        lines = []
        for d in devices:
            props = " ".join([f"{k}:{v}" for k, v in d.properties.items()])
            lines.append(f"{d.serial:22s} {d.state:10s} {props}")
        response = "\n".join(lines)
        if response:
            response += "\n"
        return OK(response.encode("utf-8"))