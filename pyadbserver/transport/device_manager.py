from __future__ import annotations

from typing import Callable, List, Optional, Protocol

from .device import Device


class DeviceService(Protocol):
    def list_devices(self) -> List[Device]:
        ...

    def get_selected(self, session_id: str) -> Optional[Device]:
        ...

    def select_device(self, session_id: str, *, serial: Optional[str] = None) -> None:
        ...

    def subscribe(self, callback: Callable[[List[Device]], None]) -> Callable[[], None]:
        ...


class SingleDeviceService:
    """A minimal single-device service.

    Keeps a single always-online device and per-session selection bookkeeping.
    """

    def __init__(self, *, device: Optional[Device] = None) -> None:
        self._device = device
        self._selected_sessions: set[str] = set()

    def list_devices(self) -> List[Device]:
        return [self._device] if self._device else []

    def get_selected(self, session_id: str) -> Optional[Device]:
        return self._device if session_id in self._selected_sessions else None

    def select_device(self, session_id: str, *, serial: Optional[str] = None) -> None:
        if self._device is None:
            raise ValueError("no device available")
        if serial is not None and serial != self._device.serial:
            raise ValueError("serial not found")
        self._selected_sessions.add(session_id)

    def subscribe(self, callback: Callable[[List[Device]], None]) -> Callable[[], None]:
        callback(self.list_devices())
        def cancel() -> None:
            return None
        return cancel


