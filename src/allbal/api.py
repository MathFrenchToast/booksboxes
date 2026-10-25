"""Application API FastAPI pour AllBAL."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from allbal.db import (
    DEFAULT_DB_PATH,
    bbox_from_radius,
    get_connection,
    get_stats,
    init_db,
    is_zone_cached,
    search_within_bbox,
    search_within_radius,
)
from allbal.deduplicate import run_deduplication
from allbal.ingest.boitesalivres_com import sync_geographic_zone

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"

ALLOWED_SCRAPE_HOSTS = {
    "www.boites-a-livres.fr",
    "boites-a-livres.fr",
}


def is_safe_http_url(url: str) -> bool:
    """Vérifie qu'une URL utilise un schéma HTTP(S) valide et possède un hôte."""
    try:
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except ValueError:
        return False


def is_allowed_scrape_url(url: str) -> bool:
    """Vérifie que l'URL à requêter côté serveur appartient aux domaines autorisés (anti-SSRF)."""
    try:
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https") and parsed.hostname in ALLOWED_SCRAPE_HOSTS
    except ValueError:
        return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialise la structure de base au démarrage
    conn = get_connection(DEFAULT_DB_PATH)
    init_db(conn)
    conn.close()
    yield


app = FastAPI(
    title="AllBAL API",
    description="Méta-API de recherche et cartographie des Boîtes à Livres en France",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "HEAD", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/api/bookcases")
def get_bookcases_near(
    lat: float = Query(
        43.490037,
        ge=-90.0,
        le=90.0,
        description="Latitude du centre de recherche (défaut: Saint-Julia 31540)",
    ),
    lon: float = Query(
        1.898538,
        ge=-180.0,
        le=180.0,
        description="Longitude du centre de recherche (défaut: Saint-Julia 31540)",
    ),
    radius_km: float = Query(20.0, ge=0.1, le=100.0, description="Rayon en kilomètres"),
    sources: str | None = Query(None, description="Filtre par sources séparées par une virgule"),
    has_photo: bool | None = Query(None, description="Filtrer uniquement les boîtes avec photo"),
    sync: bool = Query(True, description="Synchronise automatiquement la zone si non en cache"),
    limit: int = Query(500, ge=1, le=2000),
) -> dict[str, Any]:
    """Recherche les boîtes à livres dans un périmètre donné autour d'un point GPS."""
    conn = get_connection(DEFAULT_DB_PATH)
    try:
        min_lat, max_lat, min_lon, max_lon = bbox_from_radius(lat, lon, max(radius_km, 10.0))
        cached = is_zone_cached(conn, "boitesalivres_com", min_lat, max_lat, min_lon, max_lon)

        if sync and not cached:
            sync_res = sync_geographic_zone(conn, lat, lon, radius_km=radius_km)
            if sync_res["boitesalivres_fetched"] > 0 or sync_res["zonelivre_enriched"] > 0:
                run_deduplication(conn)

        sources_list = [s.strip() for s in sources.split(",") if s.strip()] if sources else None
        items = search_within_radius(
            conn,
            lat=lat,
            lon=lon,
            radius_km=radius_km,
            sources=sources_list,
            has_photo=has_photo,
            limit=limit,
        )

        return {
            "count": len(items),
            "center": {"lat": lat, "lon": lon},
            "radius_km": radius_km,
            "zone_cached": cached,
            "items": items,
        }
    finally:
        conn.close()


@app.get("/api/bookcases/bbox")
def get_bookcases_bbox(
    south: float = Query(..., ge=-90.0, le=90.0, description="Latitude sud"),
    west: float = Query(..., ge=-180.0, le=180.0, description="Longitude ouest"),
    north: float = Query(..., ge=-90.0, le=90.0, description="Latitude nord"),
    east: float = Query(..., ge=-180.0, le=180.0, description="Longitude est"),
    limit: int = Query(2000, ge=1, le=5000),
) -> dict[str, Any]:
    """Retourne les boîtes à livres situées dans un rectangle de carte (BBox)."""
    conn = get_connection(DEFAULT_DB_PATH)
    try:
        items = search_within_bbox(
            conn, south=south, west=west, north=north, east=east, limit=limit
        )
        return {
            "count": len(items),
            "bbox": {"south": south, "west": west, "north": north, "east": east},
            "items": items,
        }
    finally:
        conn.close()


@app.get("/api/stats")
def get_database_stats() -> dict[str, Any]:
    """Retourne les statistiques de la méta-base (nombres de boîtes uniques, par source, etc.)."""
    conn = get_connection(DEFAULT_DB_PATH)
    try:
        return get_stats(conn)
    finally:
        conn.close()


@app.get("/api/export.geojson")
def export_geojson(
    lat: float | None = Query(None, ge=-90.0, le=90.0),
    lon: float | None = Query(None, ge=-180.0, le=180.0),
    radius_km: float = Query(25.0, ge=0.5, le=100.0),
) -> JSONResponse:
    """Exporte les boîtes à livres (d'un périmètre ou du catalogue) au format GeoJSON standard."""
    conn = get_connection(DEFAULT_DB_PATH)
    try:
        if lat is not None and lon is not None:
            items = search_within_radius(conn, lat=lat, lon=lon, radius_km=radius_km, limit=2000)
        else:
            items = search_within_bbox(
                conn, south=-90.0, west=-180.0, north=90.0, east=180.0, limit=5000
            )

        features = []
        for item in items:
            features.append(
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [item["lon"], item["lat"]],
                    },
                    "properties": {
                        "id": item["id"],
                        "title": item["title"],
                        "address": item["address"],
                        "postcode": item["postcode"],
                        "city": item["city"],
                        "description": item["description"],
                        "photo_url": item["photo_url"],
                        "status": item["status"],
                        "source_count": item["source_count"],
                        "sources_list": item["sources_list"],
                        "distance_m": item.get("distance_m"),
                    },
                }
            )

        geojson = {
            "type": "FeatureCollection",
            "features": features,
        }
        return JSONResponse(
            content=geojson,
            media_type="application/geo+json",
            headers={"Content-Disposition": "attachment; filename=boites-a-livres.geojson"},
        )
    finally:
        conn.close()


@app.get("/api/photo/{bookcase_id}")
def get_bookcase_photo(bookcase_id: int):
    """Résout et redirige vers la photo JPEG directe d'une boîte à livres avec cache persistant en SQLite."""
    conn = get_connection(DEFAULT_DB_PATH)
    try:
        row = conn.execute(
            "SELECT id, photo_url FROM bookcases WHERE id = ?;", (bookcase_id,)
        ).fetchone()
        if not row or not row["photo_url"]:
            return Response(status_code=404)

        photo_url = row["photo_url"]
        if not is_safe_http_url(photo_url):
            return Response(status_code=404)

        # Si l'URL pointe déjà directement vers une image (ex: zonelivre ou déjà résolue)
        if (
            any(photo_url.lower().endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".webp"))
            or "/image/" in photo_url
            or "/wp-content/" in photo_url
        ):
            return RedirectResponse(url=photo_url, status_code=307)

        # Si l'URL pointe vers une fiche HTML autorisée (ex: boites-a-livres.fr/s/{id})
        if not is_allowed_scrape_url(photo_url):
            return Response(status_code=404)

        try:
            with httpx.Client(
                timeout=5.0,
                headers={"User-Agent": "AllBAL/0.1 (+https://github.com/allbal)"},
            ) as client:
                resp = client.get(photo_url, follow_redirects=True)
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    meta_og = soup.find("meta", property="og:image")
                    if meta_og and meta_og.get("content"):
                        direct_url = str(meta_og["content"]).strip()
                        if is_safe_http_url(direct_url):
                            # Mettre à jour en cache local SQLite
                            with conn:
                                conn.execute(
                                    "UPDATE bookcases SET photo_url = ? WHERE id = ?;",
                                    (direct_url, bookcase_id),
                                )
                            return RedirectResponse(url=direct_url, status_code=307)
        except httpx.HTTPError as exc:
            logger.debug("Impossible de résoudre la photo pour la boîte %s: %s", bookcase_id, exc)

        return Response(status_code=404)
    finally:
        conn.close()


# Monter les fichiers statiques HTML/JS/CSS pour l'interface cartographique
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
