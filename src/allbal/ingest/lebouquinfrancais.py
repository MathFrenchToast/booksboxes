"""Connecteur pour lebouquinfrancais.fr (Fichier statique bal.js)."""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from allbal.ingest.base import DEFAULT_RAW_DIR, download_cached

LEBOUQUINFRANCAIS_JS_URL = "https://lebouquinfrancais.fr/js_bal/bal.js"
VAR_VILLES_REGEX = re.compile(r"var\s+villes\s*=\s*(\{.*?\});", re.DOTALL)


def parse_bal_js(js_content: str) -> list[dict[str, Any]]:
    """Extrait l'objet JSON `villes` du code JavaScript et retourne les fiches normalisées."""
    match = VAR_VILLES_REGEX.search(js_content)
    if not match:
        raise ValueError(
            "Impossible de trouver la variable 'var villes = {...};' dans le fichier JS."
        )

    json_str = match.group(1)
    villes = json.loads(json_str)

    records: list[dict[str, Any]] = []
    for key, v in villes.items():
        if not isinstance(v, dict):
            continue

        raw_id = v.get("id") or key
        city = v.get("city")
        lat_val = v.get("lat")
        lon_val = v.get("lon")

        if lat_val is None or lon_val is None:
            continue

        try:
            lat = float(lat_val)
            lon = float(lon_val)
        except (ValueError, TypeError):
            continue

        # Validation des bornes géographiques valides
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            continue

        source_id = str(raw_id)
        records.append(
            {
                "source_name": "lebouquinfrancais",
                "source_id": source_id,
                "lat": lat,
                "lon": lon,
                "title": f"Boîte à livres - {city}" if city else "Boîte à livres",
                "address": None,
                "postcode": None,
                "city": city.strip() if city else None,
                "description": None,
                "photo_url": None,
                "status": None,
                "source_url": "https://lebouquinfrancais.fr/boites-a-livres.php",
                "is_enriched": 0,
            }
        )

    return records


def fetch_and_store_lebouquinfrancais(
    conn: sqlite3.Connection,
    raw_dir: Path | None = None,
    force: bool = False,
) -> int:
    """Télécharge bal.js et insère les boîtes dans raw_records."""
    if raw_dir is None:
        raw_dir = DEFAULT_RAW_DIR

    js_path = raw_dir / "lebouquinfrancais_bal.js"
    download_cached(LEBOUQUINFRANCAIS_JS_URL, js_path, force=force)

    js_content = js_path.read_text(encoding="utf-8", errors="replace")
    records = parse_bal_js(js_content)

    with conn:
        conn.executemany(
            """
            INSERT OR REPLACE INTO raw_records (
                source_name, source_id, lat, lon, title, address, postcode,
                city, description, photo_url, status, source_url, is_enriched
            ) VALUES (
                :source_name, :source_id, :lat, :lon, :title, :address, :postcode,
                :city, :description, :photo_url, :status, :source_url, :is_enriched
            );
            """,
            records,
        )

    return len(records)
