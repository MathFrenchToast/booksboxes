"""Connecteur pour boites-a-livres.fr (Dump GPX & JSON OpenStreetMap + adresses BAN)."""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from defusedxml import ElementTree as ET

from allbal.ingest.base import DEFAULT_RAW_DIR, download_cached

BOITES_GPX_URL = "https://www.boites-a-livres.fr/dumps/boites.gpx"
LIBRARIES_JSON_URL = "https://www.boites-a-livres.fr/dumps/libraries.json"

POSTCODE_CITY_REGEX = re.compile(r"^(.*?)\s+(\d{5})\s+(.+)$")


def parse_address_desc(desc: str | None) -> tuple[str | None, str | None, str | None]:
    """Parse l'adresse formatée par l'API BAN dans le champ desc du GPX."""
    if not desc:
        return None, None, None

    desc = desc.strip()
    match = POSTCODE_CITY_REGEX.match(desc)
    if match:
        street = match.group(1).strip() or None
        postcode = match.group(2).strip() or None
        city = match.group(3).strip() or None
        return street, postcode, city

    return desc, None, None


def parse_boites_gpx(
    gpx_content: str | bytes, images_map: dict[str, bool] | None = None
) -> list[dict[str, Any]]:
    """Parse le contenu XML GPX de boites-a-livres.fr et retourne la liste des fiches normalisées."""
    if images_map is None:
        images_map = {}

    root = ET.fromstring(gpx_content)
    # Gérer avec ou sans namespace XML
    records: list[dict[str, Any]] = []

    for wpt in root.iter():
        if not wpt.tag.endswith("wpt"):
            continue

        lat_str = wpt.attrib.get("lat")
        lon_str = wpt.attrib.get("lon")
        if not lat_str or not lon_str:
            continue

        try:
            lat = float(lat_str)
            lon = float(lon_str)
        except ValueError:
            continue

        name_elem = None
        desc_elem = None
        for child in wpt:
            if child.tag.endswith("name"):
                name_elem = child
            elif child.tag.endswith("desc"):
                desc_elem = child

        title = name_elem.text.strip() if name_elem is not None and name_elem.text else None
        desc_text = desc_elem.text.strip() if desc_elem is not None and desc_elem.text else None

        source_id = ""
        if title:
            # Extrait le numéro "Boite - 123"
            parts = title.split("-")
            if len(parts) >= 2:
                source_id = parts[-1].strip()
        if not source_id:
            source_id = f"{lat:.5f}_{lon:.5f}"

        address, postcode, city = parse_address_desc(desc_text)
        has_photo = images_map.get(source_id, False)
        # Si une photo est attestée, on pointe vers la fiche officielle boites-a-livres.fr qui héberge l'image
        photo_url = f"https://www.boites-a-livres.fr/s/{source_id}" if has_photo else None

        records.append(
            {
                "source_name": "boites_a_livres_fr",
                "source_id": source_id,
                "lat": lat,
                "lon": lon,
                "title": title or "Boîte à livres",
                "address": address,
                "postcode": postcode,
                "city": city,
                "description": None,
                "photo_url": photo_url,
                "status": None,
                "source_url": f"https://www.boites-a-livres.fr/s/{source_id}",
                "is_enriched": 1,
            }
        )

    return records


def fetch_and_store_boites_gpx(
    conn: sqlite3.Connection,
    raw_dir: Path | None = None,
    force: bool = False,
) -> int:
    """Télécharge boites.gpx et libraries.json et les insère dans raw_records."""
    if raw_dir is None:
        raw_dir = DEFAULT_RAW_DIR

    gpx_path = raw_dir / "boites.gpx"
    json_path = raw_dir / "libraries.json"

    download_cached(BOITES_GPX_URL, gpx_path, force=force)
    try:
        download_cached(LIBRARIES_JSON_URL, json_path, force=force)
        raw_json_data = json.loads(json_path.read_text(encoding="utf-8"))
        # raw_json_data est une liste de [lat, lon, id, has_image]
        images_map = {str(item[2]): bool(item[3]) for item in raw_json_data if len(item) >= 4}
    except Exception:
        images_map = {}

    gpx_content = gpx_path.read_bytes()
    records = parse_boites_gpx(gpx_content, images_map=images_map)

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
