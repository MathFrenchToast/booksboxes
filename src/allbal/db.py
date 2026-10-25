"""Module de base de données pour AllBAL avec indexation spatiale R*Tree."""

from __future__ import annotations

import json
import math
import sqlite3
from pathlib import Path
from typing import Any

DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "allbal.db"

EARTH_RADIUS_METERS = 6_371_000.0


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calcule la distance géodésique entre deux coordonnées en mètres (formule de Haversine)."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return EARTH_RADIUS_METERS * c


def bbox_from_radius(lat: float, lon: float, radius_km: float) -> tuple[float, float, float, float]:
    """Calcule la boîte englobante (min_lat, max_lat, min_lon, max_lon) pour un rayon donné en km."""
    delta_lat = radius_km / 111.32
    # Sécurité pour les latitudes polaires
    cos_lat = math.cos(math.radians(lat))
    if abs(cos_lat) < 1e-6:
        delta_lon = 180.0
    else:
        delta_lon = radius_km / (111.32 * cos_lat)

    min_lat = max(-90.0, lat - delta_lat)
    max_lat = min(90.0, lat + delta_lat)
    min_lon = max(-180.0, lon - delta_lon)
    max_lon = min(180.0, lon + delta_lon)

    return min_lat, max_lat, min_lon, max_lon


def get_connection(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Ouvre une connexion SQLite avec row_factory sqlite3.Row et active les clés étrangères."""
    if db_path is None:
        db_path = DEFAULT_DB_PATH
    if isinstance(db_path, str) and db_path != ":memory:":
        db_path = Path(db_path)

    if isinstance(db_path, Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path))
    else:
        conn = sqlite3.connect(db_path)

    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Initialise les tables SQLite et l'index spatial R*Tree."""
    with conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS raw_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_name TEXT NOT NULL,
                source_id TEXT NOT NULL,
                lat REAL NOT NULL,
                lon REAL NOT NULL,
                title TEXT,
                address TEXT,
                postcode TEXT,
                city TEXT,
                description TEXT,
                photo_url TEXT,
                status TEXT,
                source_url TEXT,
                is_enriched INTEGER NOT NULL DEFAULT 1,
                raw_json TEXT,
                fetched_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(source_name, source_id)
            );

            CREATE TABLE IF NOT EXISTS fetched_zones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_name TEXT NOT NULL,
                min_lat REAL NOT NULL,
                max_lat REAL NOT NULL,
                min_lon REAL NOT NULL,
                max_lon REAL NOT NULL,
                fetched_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS bookcases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lat REAL NOT NULL,
                lon REAL NOT NULL,
                title TEXT,
                address TEXT,
                postcode TEXT,
                city TEXT,
                description TEXT,
                photo_url TEXT,
                status TEXT,
                source_count INTEGER NOT NULL DEFAULT 1,
                sources_list TEXT NOT NULL,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS bookcase_sources (
                bookcase_id INTEGER NOT NULL REFERENCES bookcases(id) ON DELETE CASCADE,
                raw_record_id INTEGER NOT NULL REFERENCES raw_records(id) ON DELETE CASCADE,
                PRIMARY KEY (bookcase_id, raw_record_id)
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS bookcases_rtree USING rtree(
                id,
                min_lat, max_lat,
                min_lon, max_lon
            );

            CREATE INDEX IF NOT EXISTS idx_raw_source_enriched
                ON raw_records(source_name, is_enriched);

            CREATE INDEX IF NOT EXISTS idx_fetched_zones_source
                ON fetched_zones(source_name);
            """
        )


def is_zone_cached(
    conn: sqlite3.Connection,
    source_name: str,
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    max_age_days: int = 7,
) -> bool:
    """Vérifie si une zone géographique est déjà couverte par une synchronisation récente."""
    cursor = conn.execute(
        """
        SELECT 1 FROM fetched_zones
        WHERE source_name = ?
          AND min_lat <= ? AND max_lat >= ?
          AND min_lon <= ? AND max_lon >= ?
          AND julianday('now') - julianday(fetched_at) <= ?
        LIMIT 1;
        """,
        (source_name, min_lat, max_lat, min_lon, max_lon, max_age_days),
    )
    return cursor.fetchone() is not None


def record_zone_fetch(
    conn: sqlite3.Connection,
    source_name: str,
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
) -> None:
    """Enregistre qu'une zone géographique vient d'être synchronisée."""
    with conn:
        conn.execute(
            """
            INSERT INTO fetched_zones (source_name, min_lat, max_lat, min_lon, max_lon)
            VALUES (?, ?, ?, ?, ?);
            """,
            (source_name, min_lat, max_lat, min_lon, max_lon),
        )


def search_within_radius(
    conn: sqlite3.Connection,
    lat: float,
    lon: float,
    radius_km: float,
    sources: list[str] | None = None,
    has_photo: bool | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Recherche les boîtes à livres dans un rayon donné (en km) autour de (lat, lon)."""
    min_lat, max_lat, min_lon, max_lon = bbox_from_radius(lat, lon, radius_km)
    max_dist_m = radius_km * 1000.0

    query = """
        SELECT b.id, b.lat, b.lon, b.title, b.address, b.postcode, b.city,
               b.description, b.photo_url, b.status, b.source_count, b.sources_list, b.updated_at
        FROM bookcases b
        JOIN bookcases_rtree r ON b.id = r.id
        WHERE r.min_lat >= ? AND r.max_lat <= ?
          AND r.min_lon >= ? AND r.max_lon <= ?
    """
    params: list[Any] = [min_lat, max_lat, min_lon, max_lon]

    if has_photo:
        query += " AND b.photo_url IS NOT NULL AND b.photo_url != ''"

    rows = conn.execute(query, params).fetchall()

    results: list[dict[str, Any]] = []
    for row in rows:
        d = dict(row)
        dist_m = haversine_m(lat, lon, d["lat"], d["lon"])
        if dist_m <= max_dist_m:
            try:
                sources_list = json.loads(d["sources_list"])
            except Exception:
                sources_list = []
            d["sources_list"] = sources_list

            if sources:
                # Vérifier si au moins une source correspond
                if not any(s in sources_list for s in sources):
                    continue

            d["distance_m"] = round(dist_m, 1)
            d["distance_km"] = round(dist_m / 1000.0, 2)
            if d.get("photo_url"):
                d["photo_source_url"] = d["photo_url"]
                d["photo_url"] = f"/api/photo/{d['id']}"
            results.append(d)

    results.sort(key=lambda item: item["distance_m"])
    return results[:limit]


def search_within_bbox(
    conn: sqlite3.Connection,
    south: float,
    west: float,
    north: float,
    east: float,
    limit: int = 2000,
) -> list[dict[str, Any]]:
    """Recherche toutes les boîtes à livres dans un rectangle géographique (BBox de la carte)."""
    query = """
        SELECT b.id, b.lat, b.lon, b.title, b.address, b.postcode, b.city,
               b.description, b.photo_url, b.status, b.source_count, b.sources_list
        FROM bookcases b
        JOIN bookcases_rtree r ON b.id = r.id
        WHERE r.max_lat >= ? AND r.min_lat <= ?
          AND r.max_lon >= ? AND r.min_lon <= ?
        LIMIT ?
    """
    rows = conn.execute(query, [south, north, west, east, limit]).fetchall()
    results: list[dict[str, Any]] = []
    for row in rows:
        d = dict(row)
        try:
            d["sources_list"] = json.loads(d["sources_list"])
        except Exception:
            d["sources_list"] = []
        if d.get("photo_url"):
            d["photo_source_url"] = d["photo_url"]
            d["photo_url"] = f"/api/photo/{d['id']}"
        results.append(d)
    return results


def get_stats(conn: sqlite3.Connection) -> dict[str, Any]:
    """Retourne les statistiques de la base : nombre d'enregistrements bruts par source et boîtes consolidées."""
    raw_by_source = dict(
        conn.execute(
            "SELECT source_name, COUNT(*) FROM raw_records GROUP BY source_name;"
        ).fetchall()
    )
    total_raw = sum(raw_by_source.values())

    total_bookcases = conn.execute("SELECT COUNT(*) FROM bookcases;").fetchone()[0]
    bookcases_with_photo = conn.execute(
        "SELECT COUNT(*) FROM bookcases WHERE photo_url IS NOT NULL AND photo_url != '';"
    ).fetchone()[0]
    multi_source_count = conn.execute(
        "SELECT COUNT(*) FROM bookcases WHERE source_count > 1;"
    ).fetchone()[0]

    zones_count = conn.execute("SELECT COUNT(*) FROM fetched_zones;").fetchone()[0]

    return {
        "total_bookcases": total_bookcases,
        "total_raw_records": total_raw,
        "multi_source_bookcases": multi_source_count,
        "bookcases_with_photo": bookcases_with_photo,
        "raw_by_source": raw_by_source,
        "cached_zones_count": zones_count,
    }
