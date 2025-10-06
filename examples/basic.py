import asyncio
from pyadbserver.server import App, AdbServer, OK

app = App()

# You need to change the version to match your adb client,
# or you will get:
# adb server version (42) doesn't match this client (41); killing...
MY_ADB_VERSION = 41

@app.route('host:version')
async def version():
    return OK(f'{MY_ADB_VERSION:04x}'.encode('ascii'))

@app.route('host:devices')
async def devices():
    return OK(b'my-fake-device\tdevice\n')

server = AdbServer(app=app, port=5000) # Specify port to avoid conflict with default port 5037

async def main():
    await server.start()
    await server.serve_forever()

asyncio.run(main())