"""
Normalize edilmis arac konumu veri modeli.
Ham API alanlarini (OtobusId, Yon, KoorX, KoorY) bizim standart
normalize semamiza cevirir.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class NormalizedVehiclePosition:
    line_no: str
    vehicle_id: Optional[int]
    observed_at: str
    source_timestamp: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
    direction: Optional[int]
    raw_payload_hash: str
    is_valid: bool
    quality_flags: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "line_no": self.line_no,
            "vehicle_id": self.vehicle_id,
            "observed_at": self.observed_at,
            "source_timestamp": self.source_timestamp,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "direction": self.direction,
            "raw_payload_hash": self.raw_payload_hash,
            "is_valid": self.is_valid,
            "quality_flags": ";".join(self.quality_flags) if self.quality_flags else "",
        }
