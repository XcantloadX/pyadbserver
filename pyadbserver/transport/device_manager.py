from __future__ import annotations

from typing import Callable, List, Optional

from .device import Device


class SingleDeviceManager:
    """A minimal single-device manager.

    Keeps a single always-online device and per-session selection bookkeeping.
    """

    def __init__(self, *, device: Optional[Device] = None) -> None:
        self._device = device or Device(id="device-1", serial="device-1", state="device")
        self._selected_sessions: set[str] = set()

    def list_devices(self) -> List[Device]:
        return [self._device]

    def get_selected(self, session_id: str) -> Optional[Device]:
        return self._device if session_id in self._selected_sessions else None

    def select_device(self, session_id: str, *, serial: Optional[str] = None) -> None:
        if serial is not None and serial != self._device.serial:
            raise ValueError("serial not found")
        self._selected_sessions.add(session_id)

    def subscribe(self, callback: Callable[[List[Device]], None]) -> Callable[[], None]:
        callback(self.list_devices())
        def cancel() -> None:  # pragma: no cover - not used in M0 tests
            return None
        return cancel


