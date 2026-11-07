"""Lecture de champs GRIB2 sur grille régulière lat/lon avec ecCodes."""

from __future__ import annotations

from dataclasses import dataclass

import eccodes
import numpy as np


@dataclass
class Field:
    short_name: str
    latitudes: np.ndarray   # croissantes (sud → nord)
    longitudes: np.ndarray  # croissantes dans [-180, 180[
    values: np.ndarray      # (nlat, nlon), NaN si absente


def split_messages(data: bytes) -> list[bytes]:
    """Découpe une suite de messages GRIB concaténés."""
    messages = []
    offset = 0
    while True:
        start = data.find(b"GRIB", offset)
        if start < 0 or start + 16 > len(data):
            break
        edition = data[start + 7]
        if edition != 2:
            raise ValueError(f"GRIB édition {edition} non prise en charge")
        length = int.from_bytes(data[start + 8 : start + 16], "big")
        messages.append(data[start : start + length])
        offset = start + length
    return messages


def decode_field(message: bytes) -> Field:
    handle = eccodes.codes_new_from_message(message)
    try:
        if eccodes.codes_get(handle, "gridType") != "regular_ll":
            raise ValueError("grille non régulière")
        if eccodes.codes_get(handle, "jPointsAreConsecutive") != 0:
            raise ValueError("points rangés par colonne non pris en charge")
        ni = eccodes.codes_get(handle, "Ni")
        nj = eccodes.codes_get(handle, "Nj")
        lat1 = eccodes.codes_get(handle, "latitudeOfFirstGridPointInDegrees")
        lon1 = eccodes.codes_get(handle, "longitudeOfFirstGridPointInDegrees")
        dlat = eccodes.codes_get(handle, "jDirectionIncrementInDegrees")
        dlon = eccodes.codes_get(handle, "iDirectionIncrementInDegrees")
        j_positive = eccodes.codes_get(handle, "jScansPositively") == 1
        i_negative = eccodes.codes_get(handle, "iScansNegatively") == 1
        values = eccodes.codes_get_values(handle).astype(np.float64)
        if eccodes.codes_get(handle, "bitmapPresent"):
            missing = eccodes.codes_get(handle, "missingValue")
            values[values == missing] = np.nan
        short_name = eccodes.codes_get(handle, "shortName")
    finally:
        eccodes.codes_release(handle)

    if values.size != ni * nj:
        raise ValueError("nombre de valeurs incohérent avec la grille")
    values = values.reshape(nj, ni)

    rows = np.arange(nj)
    latitudes = lat1 + (rows if j_positive else -rows) * dlat
    columns = np.arange(ni)
    longitudes = lon1 + (-columns if i_negative else columns) * dlon
    longitudes = (longitudes + 180.0) % 360.0 - 180.0
    # Arrondi au millionième : absorbe les écarts binaires des incréments.
    latitudes = np.round(latitudes, 6)
    longitudes = np.round(longitudes, 6)

    row_order = np.argsort(latitudes, kind="stable")
    column_order = np.argsort(longitudes, kind="stable")
    return Field(
        short_name=short_name,
        latitudes=latitudes[row_order],
        longitudes=longitudes[column_order],
        values=values[np.ix_(row_order, column_order)],
    )
