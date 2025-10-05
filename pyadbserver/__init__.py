"""pyadbserver - A ADB smart-socket compatible server that allows you to implement your own ADB "device".

Exposes an asyncio-based TCP server that understands the ADB smart socket
framing and implements two host services: `host:version` and `host:kill`.

The package is structured into:
- server: networking, session handling, host services
- transport: device model and a single-device manager stub
"""

__all__ = [
    "DEFAULT_SERVER_VERSION",
]

DEFAULT_SERVER_VERSION = 41