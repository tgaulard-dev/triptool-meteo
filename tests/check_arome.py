"""Compare une tuile AROME aux fichiers GRIB bruts (vent, température, rafale, pluie).

Usage : python tests/check_arome.py <tuile .ttwx> <AAAAMMJJHH> <échéance>
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

import eccodes
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ttwx import arome  # noqa: E402
from ttwx.grib import split_messages  # noqa: E402
from ttwx.http import get  # noqa: E402
from ttwx.tiles import decode_tile  # noqa: E402

tile, run_text, step = Path(sys.argv[1]), sys.argv[2], int(sys.argv[3])
run = datetime.strptime(run_text, "%Y%m%d%H").replace(tzinfo=timezone.utc)
header, values = decode_tile(tile.read_bytes())
g = header["grid"]
names = [v["name"] for v in header["variables"]]
scales = {v["name"]: v["scale"] for v in header["variables"]}
j = header["steps"].index(step)
lookup = {}
for r in range(g["nlat"]):
    for c in range(g["nlon"]):
        lookup[(round(g["lat0"] + r * g["dlat"], 6), round(g["lon0"] + c * g["dlon"], 6))] = (r, c)

raw = {}
for package in ("SP1", "SP2"):
    for message in split_messages(get(arome.hourly_url(run, package, step))):
        h = eccodes.codes_new_from_message(message)
        key = tuple(eccodes.codes_get(h, k) for k in ("discipline", "parameterCategory", "parameterNumber"))
        it = eccodes.codes_grib_iterator_new(h, 0)
        points = {}
        while True:
            res = eccodes.codes_grib_iterator_next(it)
            if not res:
                break
            lat, lon, val = res
            if lon > 180:
                lon -= 360
            k = (round(lat, 6), round(lon, 6))
            if k in lookup:
                points[k] = val
        eccodes.codes_grib_iterator_delete(it)
        eccodes.codes_release(h)
        raw[key] = points

def compare(name, expected):
    i = names.index(name)
    worst = max(abs(values[i, j][lookup[k]] - v) for k, v in expected.items())
    ok = "OK" if worst <= scales[name] / 2 + 1e-6 else "ÉCART"
    print(f"  {name:5s} {len(expected)} points, écart max {worst:.5f} (tolérance {scales[name] / 2}) {ok}")

compare("10u", raw[arome.U10])
compare("10v", raw[arome.V10])
compare("2t", raw[arome.T2])
if arome.GUST_U in raw:
    compare("10fg", {k: np.hypot(v, raw[arome.GUST_V][k]) for k, v in raw[arome.GUST_U].items()})
if arome.RAIN in raw:
    compare("tp", {k: v + raw[arome.SNOW][k] + raw[arome.GRAUPEL][k] for k, v in raw[arome.RAIN].items()})
compare("cape", raw[arome.CAPE])
