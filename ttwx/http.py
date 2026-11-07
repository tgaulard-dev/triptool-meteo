"""Requêtes HTTP avec reprises (bibliothèque standard uniquement)."""

from __future__ import annotations

import time
import urllib.error
import urllib.request

USER_AGENT = "triptool-meteo (+https://triptool.app)"


def not_found(error: Exception) -> bool:
    return isinstance(error, urllib.error.HTTPError) and error.code == 404


def get(
    url: str,
    *,
    byte_range: tuple[int, int] | None = None,
    method: str = "GET",
    attempts: int = 4,
    timeout: float = 90,
) -> bytes:
    headers = {"User-Agent": USER_AGENT}
    if byte_range:
        headers["Range"] = f"bytes={byte_range[0]}-{byte_range[1]}"
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(url, headers=headers, method=method)
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            if error.code == 404 or attempt == attempts - 1:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt == attempts - 1:
                raise
        time.sleep(2 ** attempt)
    raise RuntimeError(f"inaccessible : {url}")
