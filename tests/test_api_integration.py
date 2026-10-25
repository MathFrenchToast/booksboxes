"""Tests d'intégration de l'API FastAPI et du service des fichiers statiques."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from allbal.api import app
from allbal.db import (
    get_connection,
    init_db,
)
from allbal.deduplicate import run_deduplication


def test_static_files_served():
    """Vérifie que index.html, style.css et app.js sont bien servis par FastAPI."""
    with TestClient(app) as client:
        # 1. Page d'accueil index.html
        res_index = client.get("/")
        assert res_index.status_code == 200
        assert "AllBAL" in res_index.text
        assert "leaflet" in res_index.text.lower()
        assert "app.js" in res_index.text

        # 2. Feuille de styles CSS
        res_css = client.get("/style.css")
        assert res_css.status_code == 200
        assert "--primary" in res_css.text

        # 3. Script JS applicatif
        res_js = client.get("/app.js")
        assert res_js.status_code == 200
        assert "api-adresse.data.gouv.fr" in res_js.text
        assert "L.map" in res_js.text


def test_api_endpoints_with_mocked_db():
    """Vérifie le bon fonctionnement des endpoints API avec une base SQLite de test."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_db = Path(tmpdir) / "test_api.db"
        conn = get_connection(test_db)
        init_db(conn)

        # Insérer quelques données brutes de test avec paramètres liés
        with conn:
            conn.execute(
                """
                INSERT INTO raw_records (
                    source_name, source_id, lat, lon, title, address, postcode, city, photo_url
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    "osm",
                    "12345",
                    48.8566,
                    2.3522,
                    "Boîte Hôtel de Ville",
                    "Place de l'Hôtel de Ville",
                    "75004",
                    "Paris",
                    "https://example.com/bal1.jpg",
                ),
            )

        # Consolidation par déduplication
        run_deduplication(conn)
        conn.close()

        with patch("allbal.api.DEFAULT_DB_PATH", test_db):
            with TestClient(app) as client:
                # 1. /api/stats
                res_stats = client.get("/api/stats")
                assert res_stats.status_code == 200
                data_stats = res_stats.json()
                assert data_stats["total_bookcases"] == 1
                assert data_stats["total_raw_records"] == 1
                assert data_stats["bookcases_with_photo"] == 1

                # 2. /api/bookcases (sans sync distante pour le test unitaire)
                res_search = client.get(
                    "/api/bookcases",
                    params={
                        "lat": 48.8560,
                        "lon": 2.3520,
                        "radius_km": 2.0,
                        "sync": "false",
                    },
                )
                assert res_search.status_code == 200
                data_search = res_search.json()
                assert data_search["count"] == 1
                assert data_search["items"][0]["title"] == "Boîte Hôtel de Ville"
                assert "distance_m" in data_search["items"][0]

                # 3. /api/bookcases/bbox
                res_bbox = client.get(
                    "/api/bookcases/bbox",
                    params={
                        "south": 48.80,
                        "west": 2.30,
                        "north": 48.90,
                        "east": 2.40,
                    },
                )
                assert res_bbox.status_code == 200
                data_bbox = res_bbox.json()
                assert data_bbox["count"] == 1

                # 4. /api/export.geojson
                res_geojson = client.get(
                    "/api/export.geojson",
                    params={
                        "lat": 48.8560,
                        "lon": 2.3520,
                        "radius_km": 2.0,
                    },
                )
                assert res_geojson.status_code == 200
                assert res_geojson.headers["content-type"] == "application/geo+json"
                geojson_data = res_geojson.json()
                assert geojson_data["type"] == "FeatureCollection"
                assert len(geojson_data["features"]) == 1
                feat = geojson_data["features"][0]
                assert feat["geometry"]["coordinates"] == [2.3522, 48.8566]
                assert feat["properties"]["title"] == "Boîte Hôtel de Ville"

                # 5. /api/photo/{id} (redirection 307 vers l'image directe)
                res_photo = client.get("/api/photo/1", follow_redirects=False)
                assert res_photo.status_code == 307
                assert res_photo.headers["location"] == "https://example.com/bal1.jpg"

                # 6. /api/photo/999 (boîte inexistante -> 404)
                res_404 = client.get("/api/photo/999")
                assert res_404.status_code == 404

                # 7. Validation des bornes géographiques (lat > 90 -> 422)
                res_invalid_coords = client.get(
                    "/api/bookcases", params={"lat": 120.0, "lon": 2.35}
                )
                assert res_invalid_coords.status_code == 422


def test_security_url_validators():
    """Vérifie les garde-fous anti-XSS et anti-SSRF sur les URLs de photos."""
    from allbal.api import is_allowed_scrape_url, is_safe_http_url

    assert is_safe_http_url("https://www.boites-a-livres.fr/image/123.jpg")
    assert not is_safe_http_url("javascript:alert(1)")
    assert not is_safe_http_url("data:text/html,<script>alert(1)</script>")
    assert not is_safe_http_url("file:///etc/passwd")

    assert is_allowed_scrape_url("https://www.boites-a-livres.fr/s/10138")
    assert not is_allowed_scrape_url("http://127.0.0.1:8000/admin")
    assert not is_allowed_scrape_url("http://169.254.169.254/latest/meta-data/")
    assert not is_allowed_scrape_url("https://evil.example.com/s/10138")
