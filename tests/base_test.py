import asyncio
import os
import contextlib
import tempfile
import unittest
from typing import List, Any

from pyadbserver.server import App, AdbServer
from pyadbserver.services.host import HostService
from pyadbserver.transport.device_manager import SingleDeviceService
from pyadbserver.transport.device import Device


class AdbServerTestCase(unittest.IsolatedAsyncioTestCase):
    """
    Base class for ADB server tests that manages server startup/shutdown
    and provides an adb command runner.
    """
    async def _run_adb(self, *args: str, timeout: float = 30.0):
        proc = await asyncio.create_subprocess_exec(
            "adb",
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self.env,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout)
        except asyncio.TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            raise
        return proc.returncode, stdout.decode("utf-8", "ignore"), stderr.decode("utf-8", "ignore")

    async def asyncSetUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmpdir = self._tmpdir.name
        
        self.server, self.fs = await self.start_server()
        port = self.server.bound_port
        assert port is not None
        self.port = port
        
        self.env = os.environ.copy()
        self.env["ANDROID_ADB_SERVER_PORT"] = str(self.port)

    async def asyncTearDown(self) -> None:
        try:
            await self.server.stop()
        finally:
            self._tmpdir.cleanup()

    def get_services(self, device_manager: SingleDeviceService) -> List[Any]:
        """
        Returns the services to be registered with the app.
        Subclasses should override this method to add their services.
        """
        return []

    async def start_server(self):
        """Starts an ADB server with the services from get_services()."""
        app = App()
        
        device_manager = SingleDeviceService(device=Device(
            id="test-device",
            serial="test-5554",
            state="device",
            properties={
                "product": "test_product",
                "model": "test_model",
                "device": "test_device",
                "transport_id": "1",
            },
        ))
        
        server = AdbServer(app=app, port=0)
        
        # Register base services
        app.register(HostService(server, device_manager))

        # Register services provided by the test class
        services = self.get_services(device_manager)
        for service in services:
            app.register(service)
        
        await server.start()
        
        # Pass back any objects the test might need, like a mock filesystem
        fs = None
        for service in services:
            if hasattr(service, "fs"):
                fs = service.fs
                break
        
        return server, fs
