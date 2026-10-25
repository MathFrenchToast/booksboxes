"""Connecteur pour boitesalivres.com (API par Bounding Box / Zone Géographique)."""

from __future__ import annotations

import sqlite3
from typing import Any

import httpx

from allbal.db import bbox_from_radius, is_zone_cached, record_zone_fetch
from allbal.ingest.base import USER_AGENT
from allbal.ingest.zonelivre import enrich_zonelivre_zone

BOITESALIVRES_BOXES_URL = "https://boitesalivres.com/api/boxes.php"


def parse_boitesalivres_data(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalise les éléments retournés par l'API JSON de boitesalivres.com."""
    records: list[dict[str, Any]] = []
    for b in items:
        raw_id = b.get("id")
        lat_val = b.get("latitude")
        lon_val = b.get("longitude")
        if raw_id is None or lat_val is None or lon_val is None:
            continue

        try:
            lat = float(lat_val)
            lon = float(lon_val)
        except (ValueError, TypeError):
            continue

        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            continue

        adresse = b.get("adresse")
        cp = b.get("cp")
        ville = b.get("ville")
        desc = b.get("description")
        photo = b.get("photo_url")
        etat = b.get("etat")

        records.append(
            {
                "source_name": "boitesalivres_com",
                "source_id": str(raw_id),
                "lat": lat,
                "lon": lon,
                "title": f"Boîte à livres - {adresse}" if adresse else "Boîte à livres",
                "address": adresse.strip() if adresse else None,
                "postcode": cp.strip() if cp else None,
                "city": ville.strip() if ville else None,
                "description": desc.strip() if desc else None,
                "photo_url": photo.strip() if photo else None,
                "status": etat.strip() if etat else None,
                "source_url": "https://boitesalivres.com/",
                "is_enriched": 1,
            }
        )
    return records


def fetch_boitesalivres_zone(
    conn: sqlite3.Connection,
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    force: bool = False,
    timeout: float = 12.0,
) -> int:
    """Interroge boitesalivres.com sur la zone géographique en 1 seule requête (si non cachée)."""
    if not force and is_zone_cached(
        conn, "boitesalivres_com", min_lat, max_lat, min_lon, max_lon, max_age_days=7
    ):
        return 0

    params = {
        "zoom": 10,
        "swlat": min_lat,
        "swlng": min_lon,
        "nelat": max_lat,
        "nelng": max_lon,
    }
    headers = {"User-Agent": USER_AGENT}

    try:
        with httpx.Client(timeout=timeout, headers=headers) as client:
            resp = client.get(BOITESALIVRES_BOXES_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        return 0

    if not data.get("success") or not isinstance(data.get("data"), list):
        return 0

    items = data["data"]
    records = parse_boitesalivres_data(items)

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
        record_zone_fetch(conn, "boitesalivres_com", min_lat, max_lat, min_lon, max_lon)

    return len(records)


def sync_geographic_zone(
    conn: sqlite3.Connection,
    lat: float,
    lon: float,
    radius_km: float = 10.0,
    force: bool = False,
) -> dict[str, int]:
    """Orchestrateur pour synchroniser et enrichir une zone géographique en au plus 2 requêtes HTTP."""
    # Marge de sécurité minimum de 10 km pour rentabiliser le cache local
    effective_radius = max(radius_km, 10.0)
    min_lat, max_lat, min_lon, max_lon = bbox_from_radius(lat, lon, effective_radius)

    b_count = fetch_boitesalivres_zone(conn, min_lat, max_lat, min_lon, max_lon, force=force)
    z_count = enrich_zonelivre_zone(conn, min_lat, max_lat, min_lon, max_lon)

    return {
        "boitesalivres_fetched": b_count,
        "zonelivre_enriched": z_count,
    }
