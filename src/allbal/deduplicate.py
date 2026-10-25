"""Moteur de déduplication et conflation spatiale des boîtes à livres."""

from __future__ import annotations

import json
import sqlite3

from allbal.db import haversine_m

DEFAULT_MERGE_RADIUS_METERS = 100.0

# Ordre de priorité des sources (de la plus fiable à la moins détaillée)
SOURCE_PRIORITY = [
    "boites_a_livres_fr",
    "boitesalivres_com",
    "zonelivre",
    "lebouquinfrancais",
    "nonmarchand",
]
SOURCE_PRIORITY_RANK = {src: idx for idx, src in enumerate(SOURCE_PRIORITY)}


def run_deduplication(
    conn: sqlite3.Connection,
    merge_radius_m: float = DEFAULT_MERGE_RADIUS_METERS,
    clear_existing: bool = True,
) -> dict[str, int]:
    """Exécute la déduplication et fusion spatiale de tous les enregistrements bruts."""
    with conn:
        if clear_existing:
            conn.execute("DELETE FROM bookcase_sources;")
            conn.execute("DELETE FROM bookcases_rtree;")
            conn.execute("DELETE FROM bookcases;")

        # Récupération de tous les enregistrements bruts avec requête statique
        raw_rows = conn.execute(
            """
            SELECT id, source_name, source_id, lat, lon, title, address,
                   postcode, city, description, photo_url, status, source_url
            FROM raw_records
            ORDER BY id ASC;
            """
        ).fetchall()

    # Tri par priorité de source puis par identifiant
    raw_rows.sort(key=lambda r: (SOURCE_PRIORITY_RANK.get(r["source_name"], 99), r["id"]))

    delta_deg = merge_radius_m / 111_000.0  # Marge d'approximation pour la BBox R*Tree

    total_processed = 0
    merged_count = 0

    with conn:
        for r in raw_rows:
            raw_id = r["id"]
            src_name = r["source_name"]
            lat = r["lat"]
            lon = r["lon"]
            title = r["title"]
            address = r["address"]
            postcode = r["postcode"]
            city = r["city"]
            description = r["description"]
            photo_url = r["photo_url"]
            status = r["status"]

            total_processed += 1

            # Recherche d'un candidat existant dans l'index R*Tree
            min_lat, max_lat = lat - delta_deg, lat + delta_deg
            min_lon, max_lon = lon - delta_deg, lon + delta_deg

            candidates = conn.execute(
                """
                SELECT b.id, b.lat, b.lon, b.title, b.address, b.postcode, b.city,
                       b.description, b.photo_url, b.status, b.source_count, b.sources_list
                FROM bookcases b
                JOIN bookcases_rtree r ON b.id = r.id
                WHERE r.min_lat >= ? AND r.max_lat <= ?
                  AND r.min_lon >= ? AND r.max_lon <= ?;
                """,
                (min_lat, max_lat, min_lon, max_lon),
            ).fetchall()

            best_match: sqlite3.Row | None = None
            min_dist = merge_radius_m

            for c in candidates:
                dist = haversine_m(lat, lon, c["lat"], c["lon"])
                if dist <= min_dist:
                    min_dist = dist
                    best_match = c

            if best_match is not None:
                # FUSION avec la boîte existante
                b_id = best_match["id"]
                merged_count += 1

                try:
                    sources = json.loads(best_match["sources_list"])
                except Exception:
                    sources = []

                if src_name not in sources:
                    sources.append(src_name)

                # Compléter les champs manquants s'ils étaient vides
                new_title = best_match["title"]
                if (
                    (not new_title or new_title == "Boîte à livres")
                    and title
                    and title != "Boîte à livres"
                ):
                    new_title = title

                new_address = best_match["address"] or address
                new_postcode = best_match["postcode"] or postcode
                new_city = best_match["city"] or city
                new_desc = best_match["description"] or description
                new_photo = best_match["photo_url"] or photo_url
                new_status = best_match["status"] or status

                conn.execute(
                    """
                    UPDATE bookcases
                    SET title = ?, address = ?, postcode = ?, city = ?,
                        description = ?, photo_url = ?, status = ?,
                        source_count = ?, sources_list = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?;
                    """,
                    (
                        new_title,
                        new_address,
                        new_postcode,
                        new_city,
                        new_desc,
                        new_photo,
                        new_status,
                        len(sources),
                        json.dumps(sources),
                        b_id,
                    ),
                )
                conn.execute(
                    """
                    INSERT OR IGNORE INTO bookcase_sources (bookcase_id, raw_record_id)
                    VALUES (?, ?);
                    """,
                    (b_id, raw_id),
                )
            else:
                # CRÉATION d'une nouvelle boîte canonique
                sources_json = json.dumps([src_name])
                cur = conn.execute(
                    """
                    INSERT INTO bookcases (
                        lat, lon, title, address, postcode, city,
                        description, photo_url, status, source_count, sources_list
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?);
                    """,
                    (
                        lat,
                        lon,
                        title or "Boîte à livres",
                        address,
                        postcode,
                        city,
                        description,
                        photo_url,
                        status,
                        sources_json,
                    ),
                )
                new_b_id = cur.lastrowid
                conn.execute(
                    "INSERT INTO bookcases_rtree VALUES (?, ?, ?, ?, ?);",
                    (new_b_id, lat, lat, lon, lon),
                )
                conn.execute(
                    """
                    INSERT INTO bookcase_sources (bookcase_id, raw_record_id)
                    VALUES (?, ?);
                    """,
                    (new_b_id, raw_id),
                )

    multi_source_count = conn.execute(
        "SELECT COUNT(*) FROM bookcases WHERE source_count > 1;"
    ).fetchone()[0]
    total_created = conn.execute("SELECT COUNT(*) FROM bookcases;").fetchone()[0]

    return {
        "raw_records_processed": total_processed,
        "bookcases_created": total_created,
        "merged_records": merged_count,
        "multi_source_bookcases": multi_source_count,
    }
