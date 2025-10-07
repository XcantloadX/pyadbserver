from typing import Dict, TYPE_CHECKING
from collections import defaultdict

from ..server.routing import OK, FAIL, device_route
if TYPE_CHECKING:
    from ..transport.device import Device


class ForwardService:
    def __init__(self):
        self.forwards: Dict[str, Dict[str, str]] = defaultdict(dict)

    @device_route("forward:norebind:<local>;<remote>")
    def forward_norebind(self, device: "Device", local: str, remote: str):
        if local in self.forwards[device.serial]:
            return FAIL("cannot rebind existing socket")
        self.forwards[device.serial][local] = remote
        return OK(b"OKAY", raw=True)

    @device_route("forward:<local>;<remote>")
    def forward(self, device: "Device", local: str, remote: str):
        self.forwards[device.serial][local] = remote
        # As for forward commands, two continuous OKAY (b"OKAYOKAY") responses are expected
        # also no length information
        return OK(b"OKAY", raw=True)

    @device_route("killforward:<local>")
    def killforward(self, device: "Device", local: str):
        if local in self.forwards[device.serial]:
            del self.forwards[device.serial][local]
        return OK(b"OKAY", raw=True)

    @device_route("killforward-all")
    def killforward_all(self, device: "Device"):
        self.forwards[device.serial].clear()
        return OK(b"OKAY", raw=True)

    @device_route("list-forward")
    def list_forward(self, device: "Device"):
        lines = [f"{device.serial} {local} {remote}" for local, remote in self.forwards[device.serial].items()]
        response = "\n".join(lines)
        if response:
            response += "\n"
        return OK(response.encode("utf-8"))