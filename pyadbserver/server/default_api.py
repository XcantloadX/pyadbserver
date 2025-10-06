from typing import TYPE_CHECKING

from .. import DEFAULT_SERVER_VERSION
from .routing import NOOP, ResponseAction, g_session, route, OK
if TYPE_CHECKING:
    from .adb_server import AdbServer
    from ..transport.device_manager import DeviceService


class HostService:
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
        """
        Returns the list of devices in a detailed format.

        Format:
        <serial> <state> <properties>
        """
        devices = self._device_manager.list_devices()
        lines = []
        for d in devices:
            props = " ".join([f"{k}:{v}" for k, v in d.properties.items()])
            lines.append(f"{d.serial:22s} {d.state:10s} {props}")
        response = "\n".join(lines)
        if response:
            response += "\n"
        return OK(response.encode("utf-8"))

    @route("host:features")
    async def features(self):
        """
        Returns the list of features supported by the server.

        Format:
        >>> host:features
        <<< OKAY
        <<< <feature1>,<feature2>,...

        Example of features:
        shell_v2,cmd,stat_v2,ls_v2,fixed_push_mkdir,apex,abb,fixed_push_symlink_timestamp,abb_exec,remount_shell,track_app,sendrecv_v2,sendrecv_v2_brotli,sendrecv_v2_lz4,sendrecv_v2_zstd,sendrecv_v2_dry_run_send,openscreen_mdns
        """
        return OK(b"shell")

    ########## Transport Commands ##########
    # Before the adb client executes any actual commands (such as shell, install, ...)
    # it will ask the ADB server to switch to a specific device.
    async def _send_transport(self, transport_id: int):
        """
        Format:
        >>> host:tport:serial:1234
        <<< OKAY
        <<< 02 00 00 00 00 00 00 00  // a 8-byte transport id (raw data, not ASCII string)
        """
        data = transport_id.to_bytes(8, "little")
        return OK(data, raw=True, action=ResponseAction.KEEP_ALIVE)
    
    @route("host:tport:serial:<serial>")
    async def transport_serial(self, serial: str):
        """
        Switch to a specific device by serial number.
        """
        self._device_manager.select_device(serial)
        return await self._send_transport(1)

    @route("host:tport:any")
    async def transport_any(self):
        """
        Switch to any device.
        """
        return await self._send_transport(2)
