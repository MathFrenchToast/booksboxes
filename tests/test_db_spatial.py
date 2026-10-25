import json

from allbal.db import (
    bbox_from_radius,
    get_connection,
    get_stats,
    haversine_m,
    init_db,
    is_zone_cached,
    record_zone_fetch,
    search_within_bbox,
    search_within_radius,
)


def test_haversine_m():
    # Distance Paris (Notre-Dame) -> Tour Eiffel ~4.2 km
    lat1, lon1 = 48.8530, 2.3499
    lat2, lon2 = 48.8584, 2.2945
    dist = haversine_m(lat1, lon1, lat2, lon2)
    assert 4000 < dist < 4500


def test_bbox_from_radius():
    min_lat, max_lat, min_lon, max_lon = bbox_from_radius(48.85, 2.35, 10.0)
    assert min_lat < 48.85 < max_lat
    assert min_lon < 2.35 < max_lon


def test_db_spatial_search():
    conn = get_connection(":memory:")
    init_db(conn)

    # Insérer une boîte à Paris Centre (point de référence)
    center_lat, center_lon = 48.8566, 2.3522

    # Point 1 : à ~1.1 km du centre (Châtelet -> Louvre)
    p1_lat, p1_lon = 48.8606, 2.3376
    # Point 2 : à ~4.2 km du centre (Tour Eiffel)
    p2_lat, p2_lon = 48.8584, 2.2945
    # Point 3 : à Lyon (>390 km)
    p3_lat, p3_lon = 45.7640, 4.8357

    with conn:
        conn.execute(
            """
            INSERT INTO bookcases (id, lat, lon, title, address, postcode, city, source_count, sources_list)
            VALUES (1, ?, ?, 'Boite Louvre', 'Rue de Rivoli', '75001', 'Paris', 2, ?);
            """,
            (p1_lat, p1_lon, json.dumps(["boites_a_livres_fr", "zonelivre"])),
        )
        conn.execute(
            "INSERT INTO bookcases_rtree VALUES (1, ?, ?, ?, ?);",
            (p1_lat, p1_lat, p1_lon, p1_lon),
        )

        conn.execute(
            """
            INSERT INTO bookcases (id, lat, lon, title, address, postcode, city, source_count, sources_list)
            VALUES (2, ?, ?, 'Boite Tour Eiffel', 'Champ de Mars', '75007', 'Paris', 1, ?);
            """,
            (p2_lat, p2_lon, json.dumps(["boitesalivres_com"])),
        )
        conn.execute(
            "INSERT INTO bookcases_rtree VALUES (2, ?, ?, ?, ?);",
            (p2_lat, p2_lat, p2_lon, p2_lon),
        )

        conn.execute(
            """
            INSERT INTO bookcases (id, lat, lon, title, address, postcode, city, source_count, sources_list)
            VALUES (3, ?, ?, 'Boite Bellecour', 'Place Bellecour', '69002', 'Lyon', 1, ?);
            """,
            (p3_lat, p3_lon, json.dumps(["lebouquinfrancais"])),
        )
        conn.execute(
            "INSERT INTO bookcases_rtree VALUES (3, ?, ?, ?, ?);",
            (p3_lat, p3_lat, p3_lon, p3_lon),
        )

    # 1. Recherche rayon 2 km : ne doit trouver que le Point 1 (Louvre)
    res_2km = search_within_radius(conn, center_lat, center_lon, radius_km=2.0)
    assert len(res_2km) == 1
    assert res_2km[0]["id"] == 1
    assert res_2km[0]["distance_m"] < 2000

    # 2. Recherche rayon 5 km : doit trouver Point 1 et Point 2, triés par distance croissante
    res_5km = search_within_radius(conn, center_lat, center_lon, radius_km=5.0)
    assert len(res_5km) == 2
    assert res_5km[0]["id"] == 1
    assert res_5km[1]["id"] == 2
    assert res_5km[0]["distance_m"] < res_5km[1]["distance_m"]

    # 3. Filtrage par source
    res_filtered = search_within_radius(
        conn, center_lat, center_lon, radius_km=5.0, sources=["boitesalivres_com"]
    )
    assert len(res_filtered) == 1
    assert res_filtered[0]["id"] == 2

    # 4. Recherche par BBox
    bbox_res = search_within_bbox(conn, south=48.8, west=2.2, north=48.9, east=2.4)
    assert len(bbox_res) == 2


def test_zone_caching():
    conn = get_connection(":memory:")
    init_db(conn)

    assert not is_zone_cached(conn, "boitesalivres_com", 48.0, 49.0, 2.0, 3.0)
    record_zone_fetch(conn, "boitesalivres_com", 47.9, 49.1, 1.9, 3.1)
    # La zone est contenue dans la zone enregistrée
    assert is_zone_cached(conn, "boitesalivres_com", 48.0, 49.0, 2.0, 3.0)
    # Une autre zone plus large n'est pas couverte
    assert not is_zone_cached(conn, "boitesalivres_com", 45.0, 50.0, 1.0, 4.0)


def test_get_stats():
    conn = get_connection(":memory:")
    init_db(conn)
    with conn:
        conn.execute(
            """
            INSERT INTO raw_records (source_name, source_id, lat, lon)
            VALUES ('boites_a_livres_fr', '1', 48.8, 2.3),
                   ('boites_a_livres_fr', '2', 48.9, 2.4),
                   ('zonelivre', '10', 48.8, 2.3);
            """
        )
    stats = get_stats(conn)
    assert stats["total_raw_records"] == 3
    assert stats["raw_by_source"]["boites_a_livres_fr"] == 2
    assert stats["raw_by_source"]["zonelivre"] == 1
