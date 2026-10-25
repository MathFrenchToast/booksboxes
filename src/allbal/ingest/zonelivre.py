"""Connecteur pour boite.a.livres.zonelivre.fr (GeoDirectory REST API v2)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import httpx

from allbal.ingest.base import DEFAULT_RAW_DIR, USER_AGENT, download_cached

ZONELIVRE_MARKERS_URL = (
    "https://boite.a.livres.zonelivre.fr/wp-json/geodir/v2/markers?post_type=gd_place"
)
ZONELIVRE_LIEU_URL = "https://boite.a.livres.zonelivre.fr/wp-json/geodir/v2/lieu"


def parse_zonelivre_markers(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse la réponse de l'endpoint /markers de GeoDirectory."""
    items = data.get("items", [])
    records: list[dict[str, Any]] = []

    for item in items:
        source_id = str(item.get("m", "")).strip()
        lat_val = item.get("lt")
        lon_val = item.get("ln")
        city_title = item.get("t")

        if not source_id or lat_val is None or lon_val is None:
            continue

        try:
            lat = float(lat_val)
            lon = float(lon_val)
        except (ValueError, TypeError):
            continue

        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            continue

        records.append(
            {
                "source_name": "zonelivre",
                "source_id": source_id,
                "lat": lat,
                "lon": lon,
                "title": f"Boîte à livres - {city_title}" if city_title else "Boîte à livres",
                "address": None,
                "postcode": None,
                "city": city_title.strip() if city_title else None,
                "description": None,
                "photo_url": None,
                "status": None,
                "source_url": f"https://boite.a.livres.zonelivre.fr/?p={source_id}",
                "is_enriched": 0,
            }
        )

    return records


def fetch_and_store_zonelivre_markers(
    conn: sqlite3.Connection,
    raw_dir: Path | None = None,
    force: bool = False,
) -> int:
    """Télécharge l'ensemble des 9 217 marqueurs en 1 seule requête HTTP et les insère dans raw_records."""
    if raw_dir is None:
        raw_dir = DEFAULT_RAW_DIR

    json_path = raw_dir / "zonelivre_markers.json"
    download_cached(ZONELIVRE_MARKERS_URL, json_path, force=force)

    data = json.loads(json_path.read_text(encoding="utf-8"))
    records = parse_zonelivre_markers(data)

    with conn:
        conn.executemany(
            """
            INSERT INTO raw_records (
                source_name, source_id, lat, lon, title, address, postcode,
                city, description, photo_url, status, source_url, is_enriched
            ) VALUES (
                :source_name, :source_id, :lat, :lon, :title, :address, :postcode,
                :city, :description, :photo_url, :status, :source_url, :is_enriched
            )
            ON CONFLICT(source_name, source_id) DO UPDATE SET
                lat=excluded.lat,
                lon=excluded.lon,
                city=COALESCE(raw_records.city, excluded.city),
                title=COALESCE(raw_records.title, excluded.title);
            """,
            records,
        )

    return len(records)


def enrich_zonelivre_zone(
    conn: sqlite3.Connection,
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    limit: int = 100,
) -> int:
    """Récupère l'adresse exacte et la photo en 1 seule requête groupée pour les boîtes zonelivre d'un secteur."""
    cursor = conn.execute(
        """
        SELECT source_id FROM raw_records
        WHERE source_name = 'zonelivre'
          AND is_enriched = 0
          AND lat BETWEEN ? AND ?
          AND lon BETWEEN ? AND ?
        LIMIT ?;
        """,
        (min_lat, max_lat, min_lon, max_lon, limit),
    )
    rows = cursor.fetchall()
    if not rows:
        return 0

    ids = [str(r["source_id"]) for r in rows]
    ids_str = ",".join(ids)

    url = f"{ZONELIVRE_LIEU_URL}?include={ids_str}&per_page={len(ids)}"
    headers = {"User-Agent": USER_AGENT}

    try:
        with httpx.Client(timeout=15.0, headers=headers) as client:
            resp = client.get(url)
            resp.raise_for_status()
            items = resp.json()
    except Exception:
        return 0

    enriched_count = 0
    with conn:
        for item in items:
            source_id = str(item.get("id"))
            street = item.get("street")
            city = item.get("city")
            zipcode = item.get("zip")
            link = item.get("link")
            featured = item.get("featured_image")
            photo_url = featured.get("src") if isinstance(featured, dict) else None

            conn.execute(
                """
                UPDATE raw_records
                SET address = COALESCE(?, address),
                    postcode = COALESCE(?, postcode),
                    city = COALESCE(?, city),
                    source_url = COALESCE(?, source_url),
                    photo_url = COALESCE(?, photo_url),
                    is_enriched = 1
                WHERE source_name = 'zonelivre' AND source_id = ?;
                """,
                (street, zipcode, city, link, photo_url, source_id),
            )
            enriched_count += 1

    return enriched_count
