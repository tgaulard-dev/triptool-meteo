"""Écriture et lecture des tuiles .ttwx (voir FORMAT.md)."""

from __future__ import annotations

import json
import struct
import zlib
from dataclasses import dataclass

import numpy as np

MAGIC = b"TTWX"
VERSION = 1
MISSING = -32768
TILE_DEGREES = 5


@dataclass(frozen=True)
class Variable:
    name: str
    units: str
    scale: float
    offset: float

    def quantize(self, values: np.ndarray) -> np.ndarray:
        raw = np.round((values - self.offset) / self.scale)
        out = np.full(values.shape, MISSING, dtype="<i2")
        valid = np.isfinite(raw) & (raw > MISSING) & (raw <= 32767)
        out[valid] = raw[valid].astype("<i2")
        return out


def tile_name(lat0: int, lon0: int) -> str:
    ns = "N" if lat0 >= 0 else "S"
    ew = "E" if lon0 >= 0 else "W"
    return f"{ns}{abs(lat0):02d}{ew}{abs(lon0):03d}"


def tile_origin(latitude: float, longitude: float) -> tuple[int, int]:
    """Coin sud-ouest de la tuile qui contient ce point."""
    lat0 = int(np.floor(latitude / TILE_DEGREES)) * TILE_DEGREES
    lat0 = min(lat0, 90 - TILE_DEGREES)  # la latitude 90 rejoint N85
    lon0 = int(np.floor(longitude / TILE_DEGREES)) * TILE_DEGREES
    return lat0, lon0


def deflate(data: bytes) -> bytes:
    compressor = zlib.compressobj(level=9, wbits=-15)
    return compressor.compress(data) + compressor.flush()


def inflate(data: bytes) -> bytes:
    return zlib.decompress(data, wbits=-15)


def encode_tile(
    *,
    model: str,
    run: str,
    steps: list[int],
    variables: list[Variable],
    lat0: float,
    lon0: float,
    dlat: float,
    dlon: float,
    data: np.ndarray,
) -> bytes:
    """`data` : int16 de forme (variables, échéances, nlat, nlon), sud→nord, ouest→est."""
    if data.dtype != np.dtype("<i2"):
        raise ValueError("données int16 petit-boutistes attendues")
    nvar, nstep, nlat, nlon = data.shape
    if nvar != len(variables) or nstep != len(steps):
        raise ValueError("forme des données incohérente avec l'en-tête")
    header = {
        "model": model,
        "run": run,
        "steps": steps,
        "grid": {
            "lat0": lat0,
            "lon0": lon0,
            "dlat": dlat,
            "dlon": dlon,
            "nlat": nlat,
            "nlon": nlon,
        },
        "variables": [
            {"name": v.name, "units": v.units, "scale": v.scale, "offset": v.offset}
            for v in variables
        ],
        "missing": MISSING,
    }
    header_bytes = json.dumps(header, separators=(",", ":")).encode("utf-8")
    payload = (
        MAGIC
        + struct.pack("<HI", VERSION, len(header_bytes))
        + header_bytes
        + np.ascontiguousarray(data).tobytes()
    )
    return deflate(payload)


def decode_tile(blob: bytes) -> tuple[dict, np.ndarray]:
    """Renvoie l'en-tête et les valeurs physiques (float64, NaN si absentes)."""
    payload = inflate(blob)
    if payload[:4] != MAGIC:
        raise ValueError("signature TTWX absente")
    version, header_length = struct.unpack_from("<HI", payload, 4)
    if version != VERSION:
        raise ValueError(f"version {version} non prise en charge")
    start = 10
    header = json.loads(payload[start : start + header_length])
    grid = header["grid"]
    shape = (len(header["variables"]), len(header["steps"]), grid["nlat"], grid["nlon"])
    raw = np.frombuffer(payload, dtype="<i2", offset=start + header_length).reshape(shape)
    values = raw.astype(np.float64)
    for index, variable in enumerate(header["variables"]):
        values[index] = variable["offset"] + values[index] * variable["scale"]
    values[raw == header["missing"]] = np.nan
    return header, values
