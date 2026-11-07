"""Assemble un cycle de modèle et l'écrit en tuiles .ttwx."""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from . import ecmwf
from .grib import decode_field, split_messages
from .tiles import MISSING, TILE_DEGREES, encode_tile, tile_name

log = logging.getLogger(__name__)


def run_id(run: datetime) -> str:
    return run.strftime("%Y%m%d%H")


def run_iso(run: datetime) -> str:
    return run.strftime("%Y-%m-%dT%H:%M:%SZ")


def produce_ecmwf(
    run: datetime,
    out_dir: Path,
    *,
    steps: list[int] | None = None,
    bbox: tuple[float, float, float, float] | None = None,
    workers: int = 6,
) -> Path:
    """Télécharge le cycle, écrit les tuiles et le manifest. Renvoie le dossier du cycle.

    `bbox` (lat min, lon min, lat max, lon max) limite les tuiles écrites, pour les essais.
    """
    steps = steps or ecmwf.forecast_steps()
    variables = ecmwf.VARIABLES
    names = [variable.name for variable in variables]
    cube: np.ndarray | None = None
    latitudes = longitudes = None

    with ThreadPoolExecutor(max_workers=workers) as pool:
        downloads = {step: pool.submit(ecmwf.download_step, run, step) for step in steps}
        # Décodage dans ce fil, dans l'ordre : ecCodes n'est pas sollicité en parallèle.
        for step_index, step in enumerate(steps):
            data = downloads[step].result()
            for message in split_messages(data):
                field = decode_field(message)
                field.short_name = ecmwf.canonical_name(field.short_name)
                if field.short_name not in names:
                    continue
                if cube is None:
                    latitudes, longitudes = field.latitudes, field.longitudes
                    shape = (len(variables), len(steps), len(latitudes), len(longitudes))
                    cube = np.full(shape, MISSING, dtype="<i2")
                elif not (np.array_equal(latitudes, field.latitudes)
                          and np.array_equal(longitudes, field.longitudes)):
                    raise RuntimeError(f"h+{step} : grille différente pour {field.short_name}")
                variable_index = names.index(field.short_name)
                cube[variable_index, step_index] = variables[variable_index].quantize(field.values)
            log.info("h+%d décodée (%d/%d)", step, step_index + 1, len(steps))

    if cube is None:
        raise RuntimeError("aucun champ décodé")

    run_dir = out_dir / ecmwf.MODEL / run_id(run)
    run_dir.mkdir(parents=True, exist_ok=True)
    dlat = float(latitudes[1] - latitudes[0])
    dlon = float(longitudes[1] - longitudes[0])
    count = 0
    for lat0 in range(-90, 90, TILE_DEGREES):
        if bbox and (lat0 + TILE_DEGREES <= bbox[0] or lat0 >= bbox[2]):
            continue
        upper = lat0 + TILE_DEGREES
        rows = np.where((latitudes >= lat0) & ((latitudes < upper) | (upper == 90)))[0]
        if rows.size == 0:
            continue
        for lon0 in range(-180, 180, TILE_DEGREES):
            if bbox and (lon0 + TILE_DEGREES <= bbox[1] or lon0 >= bbox[3]):
                continue
            columns = np.where((longitudes >= lon0) & (longitudes < lon0 + TILE_DEGREES))[0]
            if columns.size == 0:
                continue
            block = cube[:, :, rows[0] : rows[-1] + 1, columns[0] : columns[-1] + 1]
            blob = encode_tile(
                model=ecmwf.MODEL,
                run=run_iso(run),
                steps=steps,
                variables=variables,
                lat0=float(latitudes[rows[0]]),
                lon0=float(longitudes[columns[0]]),
                dlat=dlat,
                dlon=dlon,
                data=block,
            )
            (run_dir / f"{tile_name(lat0, lon0)}.ttwx").write_bytes(blob)
            count += 1

    manifest = {
        "format": 1,
        "model": ecmwf.MODEL,
        "run": run_iso(run),
        "steps": steps,
        "tileDegrees": TILE_DEGREES,
        "variables": names,
        "tiles": count,
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    log.info("%d tuiles écrites dans %s", count, run_dir)
    return run_dir
