import asyncio
from pyadbserver.server import App, AdbServer, route, OK

MY_ADB_VERSION = 41

app = App()

class MyDeviceService:
    def __init__(self) -> None:
        self._devices: list[tuple[str, str]] = []

    # This route is always required
    @route('host:version')
    async def version(self):
        return OK(f'{MY_ADB_VERSION:04x}'.encode('ascii'))

    @route('host:devices')
    async def devices(self):
        lines = [f'{d[0]}\t{d[1]}' for d in self._devices]
        response = '\n'.join(lines)
        if response:
            response += '\n'
        return OK(response.encode('ascii'))
    
    def connect(self, serial: str, state: str):
        self._devices.append((serial, state))
    
    def disconnect(self, serial: str):
        self._devices = [d for d in self._devices if d[0] != serial]

device_service = MyDeviceService()
device_service.connect('my-fake-device', 'device')
device_service.connect('my-fake-device-2', 'recovery')
device_service.connect('my-fake-device-3', 'unauthorized')
app.register(device_service)

server = AdbServer(app=app, port=5000)
async def main():
    await server.start()
    print(f"Server started on port {server.bound_port}")
    await server.serve_forever()

asyncio.run(main())