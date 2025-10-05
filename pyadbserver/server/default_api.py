from .adb_server import AdbServer

from .. import DEFAULT_SERVER_VERSION
from .routing import route, OK


class DefaultAPI:
    def __init__(self, adb_server: 'AdbServer') -> None:
        self._adb_server = adb_server

    @route("host:version")
    async def version(self):
        return OK(f"{DEFAULT_SERVER_VERSION:04x}".encode("ascii"))

    @route("host:kill")
    async def kill(self):
        self._adb_server.request_shutdown()
        return OK()