import asyncio
import os

from pyadbserver.server import AdbServer


async def _main() -> None:
    host = "127.0.0.1"
    port = int(os.environ.get("ADB_SERVER_PORT", "5037"))
    server = AdbServer(host=host, port=port)
    await server.start()
    print(f"pyadbserver listening on {host}:{server.bound_port}")
    try:
        await server.serve_forever()
    finally:
        await server.stop()


if __name__ == "__main__":
    asyncio.run(_main())

def main():
    print("Hello from pyadbserver!")


if __name__ == "__main__":
    main()
