"""Ligne de commande : python -m ttwx produce --model ecmwf --out build"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone
from pathlib import Path

from . import ecmwf
from .produce import produce_ecmwf, run_id


def main() -> None:
    parser = argparse.ArgumentParser(prog="ttwx")
    commands = parser.add_subparsers(dest="command", required=True)

    latest = commands.add_parser("latest-run", help="affiche le dernier cycle complet (AAAAMMJJHH)")
    latest.add_argument("--model", choices=["ecmwf"], default="ecmwf")

    remote = commands.add_parser("remote-latest", help="cycle publié sur R2 (vide si aucun)")
    remote.add_argument("--model", choices=["ecmwf"], default="ecmwf")

    publish = commands.add_parser("publish", help="envoie un cycle produit sur R2")
    publish.add_argument("run_dir", type=Path)
    publish.add_argument("--keep", type=int, default=2, help="cycles conservés")

    produce = commands.add_parser("produce", help="télécharge un cycle et écrit ses tuiles")
    produce.add_argument("--model", choices=["ecmwf"], default="ecmwf")
    produce.add_argument("--out", type=Path, default=Path("build"))
    produce.add_argument("--run", help="AAAAMMJJHH ; par défaut le dernier cycle complet")
    produce.add_argument("--steps", help="échéances séparées par des virgules (essais)")
    produce.add_argument("--bbox", help="latmin,lonmin,latmax,lonmax : tuiles écrites (essais)")
    produce.add_argument("--workers", type=int, default=6)

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.command == "latest-run":
        print(run_id(ecmwf.latest_complete_run()))
        return

    if args.command == "remote-latest":
        from .publish import remote_latest

        manifest = remote_latest(args.model)
        print(run_id(datetime.strptime(manifest["run"], "%Y-%m-%dT%H:%M:%SZ")) if manifest else "")
        return

    if args.command == "publish":
        from .publish import publish_run

        publish_run(args.run_dir, keep=args.keep)
        return

    run = (
        datetime.strptime(args.run, "%Y%m%d%H").replace(tzinfo=timezone.utc)
        if args.run
        else ecmwf.latest_complete_run()
    )
    steps = [int(value) for value in args.steps.split(",")] if args.steps else None
    bbox = tuple(float(value) for value in args.bbox.split(",")) if args.bbox else None
    produce_ecmwf(run, args.out, steps=steps, bbox=bbox, workers=args.workers)


if __name__ == "__main__":
    main()
