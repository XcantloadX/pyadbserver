from typing import Dict

from ..server import OK, FAIL, route
from ..transport.device_manager import SingleDeviceService


class ForwardService:
    def __init__(self, device_manager: SingleDeviceService):
        self.forwards: Dict[str, str] = {}
        self.device_manager = device_manager

    @route("<host>:forward:norebind:<local>;<remote>")
    def forward_norebind(self, host: str, local: str, remote: str):
        if local in self.forwards:
            return FAIL("cannot rebind existing socket")
        self.forwards[local] = remote
        return OK(b"OKAY", raw=True)

    @route("<host>:forward:<local>;<remote>")
    def forward(self, host: str, local: str, remote: str):
        self.forwards[local] = remote
        # As for forward commands, two continuous OKAY (b"OKAYOKAY") responses are expected
        # also no length information
        return OK(b"OKAY", raw=True)

    @route("<host>:killforward:<local>")
    def killforward(self, host: str, local: str):
        if local in self.forwards:
            del self.forwards[local]
        return OK(b"OKAY", raw=True)

    @route("<host>:killforward-all")
    def killforward_all(self, host: str):
        self.forwards.clear()
        return OK(b"OKAY", raw=True)

    @route("<host>:list-forward")
    def list_forward(self, host: str):
        devices = self.device_manager.list_devices()
        if not devices:
            return OK(b"")
        serial = devices[0].serial
        lines = [f"{serial} {local} {remote}" for local, remote in self.forwards.items()]
        response = "\n".join(lines)
        if response:
            response += "\n"
        return OK(response.encode("utf-8"))