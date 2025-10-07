from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class Device:
    id: str
    serial: str
    state: str = "device"  # device|offline|recovery|bootloader
    properties: Dict[str, str] = field(default_factory=dict)
    features: List[bytes] = field(default_factory=list)


