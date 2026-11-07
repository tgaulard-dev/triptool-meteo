"""Compare des tuiles produites aux valeurs lues directement dans le GRIB.

Usage : python tests/check_against_grib.py <dossier du cycle> <AAAAMMJJHH> <échéance>
Coordonnées et valeurs comparées à celles de l'itérateur ecCodes (ce que lit l'app).
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

import eccodes
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ttwx import ecmwf  # noqa: E402
from ttwx.grib import split_messages  # noqa: E402
from ttwx.tiles import decode_tile  # noqa: E402

run_dir, run_text, step = Path(sys.argv[1]), sys.argv[2], int(sys.argv[3])
run = datetime.strptime(run_text, "%Y%m%d%H").replace(tzinfo=timezone.utc)

tiles = {}
for path in sorted(run_dir.glob("*.ttwx")):
    header, values = decode_tile(path.read_bytes())
    tiles[path.stem] = (header, values)
header0 = next(iter(tiles.values()))[0]
step_index = header0["steps"].index(step)
names = [v["name"] for v in header0["variables"]]
scales = {v["name"]: v["scale"] for v in header0["variables"]}

# Points des tuiles : (lat, lon) -> valeurs par variable.
points = {}
for header, values in tiles.values():
    g = header["grid"]
    for r in range(g["nlat"]):
        for c in range(g["nlon"]):
            key = (round(g["lat0"] + r * g["dlat"], 6), round(g["lon0"] + c * g["dlon"], 6))
            points[key] = values[:, step_index, r, c]

worst = {}
checked = 0
for message in split_messages(ecmwf.download_step(run, step)):
    handle = eccodes.codes_new_from_message(message)
    name = ecmwf.canonical_name(eccodes.codes_get(handle, "shortName"))
    index = names.index(name)
    iterator = eccodes.codes_grib_iterator_new(handle, 0)
    found = 0
    while True:
        result = eccodes.codes_grib_iterator_next(iterator)
        if not result:
            break
        lat, lon, value = result
        if lon > 180:
            lon -= 360
        key = (round(lat, 6), round(lon, 6))
        if key not in points:
            continue
        found += 1
        error = abs(points[key][index] - value)
        worst[name] = max(worst.get(name, 0.0), error)
    eccodes.codes_grib_iterator_delete(iterator)
    eccodes.codes_release(handle)
    checked += found

print(f"{len(points)} points de tuile, {checked} comparaisons")
for name in names:
    if name in worst:
        verdict = "OK" if worst[name] <= scales[name] / 2 + 1e-9 else "ÉCART"
        print(f"  {name:5s} écart max {worst[name]:.6f} (tolérance {scales[name] / 2}) {verdict}")
