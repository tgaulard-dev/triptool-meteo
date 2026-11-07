"""Publication des tuiles sur Cloudflare R2 (API compatible S3).

Variables d'environnement : R2_ACCOUNT_ID, R2_ACCESS_KEY_ID,
R2_SECRET_ACCESS_KEY, R2_BUCKET. Les secrets restent dans GitHub, jamais
dans le dépôt.
"""

from __future__ import annotations

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

log = logging.getLogger(__name__)

# Un cycle publié ne change plus : cache long. latest.json change à chaque cycle.
IMMUTABLE = "public, max-age=604800, immutable"
SHORT = "public, max-age=300"


def _client():
    account = os.environ["R2_ACCOUNT_ID"]
    return boto3.client(
        "s3",
        endpoint_url=f"https://{account}.r2.cloudflarestorage.com",
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
        config=Config(retries={"max_attempts": 8, "mode": "adaptive"}, max_pool_connections=32),
    )


def _bucket() -> str:
    return os.environ["R2_BUCKET"]


def remote_latest(model: str) -> dict | None:
    try:
        body = _client().get_object(Bucket=_bucket(), Key=f"{model}/latest.json")["Body"].read()
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
            return None
        raise
    return json.loads(body)


def publish_run(run_dir: Path, *, keep: int = 2, workers: int = 16) -> None:
    """Envoie les tuiles, puis le manifest, puis latest.json, puis purge les vieux cycles."""
    manifest = json.loads((run_dir / "manifest.json").read_text())
    model = manifest["model"]
    run_id = run_dir.name
    prefix = f"{model}/{run_id}"
    client = _client()
    bucket = _bucket()

    tiles = sorted(run_dir.glob("*.ttwx"))
    if len(tiles) != manifest["tiles"]:
        raise RuntimeError(f"{len(tiles)} tuiles sur disque, {manifest['tiles']} annoncées")

    def upload(path: Path) -> None:
        client.put_object(
            Bucket=bucket,
            Key=f"{prefix}/{path.name}",
            Body=path.read_bytes(),
            ContentType="application/octet-stream",
            CacheControl=IMMUTABLE,
        )

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for _ in pool.map(upload, tiles):
            pass
    log.info("%d tuiles envoyées dans %s", len(tiles), prefix)

    body = json.dumps(manifest, indent=2).encode()
    client.put_object(Bucket=bucket, Key=f"{prefix}/manifest.json", Body=body,
                      ContentType="application/json", CacheControl=IMMUTABLE)
    # En dernier : l'app ne voit le cycle qu'une fois toutes ses tuiles en ligne.
    client.put_object(Bucket=bucket, Key=f"{model}/latest.json", Body=body,
                      ContentType="application/json", CacheControl=SHORT)
    log.info("latest.json → %s", run_id)

    _purge_old_runs(client, bucket, model, keep=keep)


def _purge_old_runs(client, bucket: str, model: str, *, keep: int) -> None:
    listing = client.list_objects_v2(Bucket=bucket, Prefix=f"{model}/", Delimiter="/")
    runs = sorted(
        entry["Prefix"].rstrip("/").split("/")[-1]
        for entry in listing.get("CommonPrefixes", [])
    )
    for run_id in runs[:-keep] if len(runs) > keep else []:
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=f"{model}/{run_id}/"):
            keys = [{"Key": item["Key"]} for item in page.get("Contents", [])]
            for start in range(0, len(keys), 1000):
                client.delete_objects(Bucket=bucket, Delete={"Objects": keys[start:start + 1000]})
        log.info("cycle %s/%s supprimé", model, run_id)
