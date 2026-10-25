"""Connecteur pour nonmarchand.org (Page Wiki EspacesDeGratuite)."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

from allbal.ingest.base import DEFAULT_RAW_DIR, download_cached

NONMARCHAND_URL = (
    "https://nonmarchand.org/pmwiki/EspacesDeGratuite/RechercheCarteBo%C3%AEte%C3%80Livres"
)


def parse_nonmarchand_html(html_content: str) -> list[dict[str, Any]]:
    """Parse la liste des points dans <dl class='map'> du wiki PmWiki."""
    soup = BeautifulSoup(html_content, "html.parser")
    dl = soup.find("dl", class_="map")
    if not dl:
        return []

    records: list[dict[str, Any]] = []
    dts = dl.find_all("dt")

    for dt in dts:
        dd = dt.find_next_sibling("dd")
        dt_text = dt.get_text(strip=True)
        if not dt_text or "center=" in dt_text:
            continue

        # Format typique : "45.89824/-0.95395" ou "44.38767,-0.72372"
        coords_match = re.search(r"(-?\d+\.\d+)\s*[/,]\s*(-?\d+\.\d+)", dt_text)
        if not coords_match:
            continue

        try:
            lat = float(coords_match.group(1))
            lon = float(coords_match.group(2))
        except ValueError:
            continue

        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            continue

        # Ignorer le point d'aide 0.3, -3.4
        if abs(lat - 0.3) < 0.01 and abs(lon - (-3.4)) < 0.01:
            continue

        title = "Boîte à livres"
        source_url = NONMARCHAND_URL
        source_id = f"{lat:.5f}_{lon:.5f}"

        if dd:
            a_tag = dd.find("a")
            if a_tag:
                title = a_tag.get_text(strip=True) or title
                source_url = a_tag.get("href") or source_url
                # ID dérivé de l'URL de la page (ex: 20130916691)
                page_id = source_url.rstrip("/").split("/")[-1]
                if page_id:
                    source_id = page_id

        records.append(
            {
                "source_name": "nonmarchand",
                "source_id": source_id,
                "lat": lat,
                "lon": lon,
                "title": title,
                "address": None,
                "postcode": None,
                "city": None,
                "description": None,
                "photo_url": None,
                "status": None,
                "source_url": source_url,
                "is_enriched": 1,
            }
        )

    return records


def fetch_and_store_nonmarchand(
    conn: sqlite3.Connection,
    raw_dir: Path | None = None,
    force: bool = False,
) -> int:
    """Télécharge la page HTML de nonmarchand.org et insère les boîtes dans raw_records."""
    if raw_dir is None:
        raw_dir = DEFAULT_RAW_DIR

    html_path = raw_dir / "nonmarchand.html"
    download_cached(NONMARCHAND_URL, html_path, force=force)

    html_content = html_path.read_text(encoding="utf-8", errors="replace")
    records = parse_nonmarchand_html(html_content)

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
