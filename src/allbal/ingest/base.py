"""Utilitaires de téléchargement avec mise en cache disque pour les connecteurs d'ingestion."""

from __future__ import annotations

import time
from pathlib import Path

import httpx

DEFAULT_RAW_DIR = Path(__file__).resolve().parents[3] / "data" / "raw"
USER_AGENT = "AllBAL-MetaBookcases/0.1 (+https://github.com/allbal; contact@mathieu.dev)"


def download_cached(
    url: str,
    target_path: Path,
    max_age_days: int = 30,
    force: bool = False,
    timeout: float = 30.0,
) -> Path:
    """Télécharge une URL vers target_path uniquement si le fichier n'existe pas ou est trop ancien."""
    target_path.parent.mkdir(parents=True, exist_ok=True)

    if not force and target_path.exists():
        age_days = (time.time() - target_path.stat().st_mtime) / 86400.0
        if age_days < max_age_days:
            return target_path

    headers = {"User-Agent": USER_AGENT}
    with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
        response = client.get(url)
        response.raise_for_status()
        target_path.write_bytes(response.content)

    return target_path
