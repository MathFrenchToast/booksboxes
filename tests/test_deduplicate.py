import json

from allbal.db import get_connection, init_db
from allbal.deduplicate import DEFAULT_MERGE_RADIUS_METERS, run_deduplication


def test_deduplication_merge():
    conn = get_connection(":memory:")
    init_db(conn)

    # 1. Point source OSM (boites-a-livres.fr) : lat=48.85000, lon=2.35000 avec adresse BAN et photo
    # 2. Point source boitesalivres.com : lat=48.85010, lon=2.35005 (~11 mètres d'écart) avec statut 'pleine'
    # 3. Point source lebouquinfrancais : lat=48.85060, lon=2.35000 (~67 mètres d'écart) -> fusionne avec le rayon de 100 m
    # 4. Point source zonelivre : lat=48.85300, lon=2.35000 (~333 mètres d'écart) -> reste distinct (> 100 m)
    with conn:
        conn.execute(
            """
            INSERT INTO raw_records (source_name, source_id, lat, lon, title, address, postcode, city, photo_url)
            VALUES ('boites_a_livres_fr', '101', 48.85000, 2.35000, 'Boîte Saint-Paul', '10 Rue Saint-Paul', '75004', 'Paris', 'https://example.com/p1.jpg');
            """
        )
        conn.execute(
            """
            INSERT INTO raw_records (source_name, source_id, lat, lon, title, status, description)
            VALUES ('boitesalivres_com', 'bal-202', 48.85010, 2.35005, 'Cabane à livres', 'pleine', 'Proche métro');
            """
        )
        conn.execute(
            """
            INSERT INTO raw_records (source_name, source_id, lat, lon, title, city)
            VALUES ('lebouquinfrancais', 'lbf-404', 48.85060, 2.35000, 'Boîte Quai', 'Paris');
            """
        )
        conn.execute(
            """
            INSERT INTO raw_records (source_name, source_id, lat, lon, title, city)
            VALUES ('zonelivre', 'zone-303', 48.85300, 2.35000, 'Boîte Marais', 'Paris');
            """
        )

    # Exécution avec le rayon par défaut (100 mètres)
    assert DEFAULT_MERGE_RADIUS_METERS == 100.0
    res = run_deduplication(conn)

    assert res["raw_records_processed"] == 4
    assert (
        res["bookcases_created"] == 2
    )  # 2 créées au lieu de 4 (3 ont fusionné ensemble, 1 reste distincte)
    assert res["merged_records"] == 2
    assert res["multi_source_bookcases"] == 1

    # Vérification des attributs de la boîte fusionnée (recoupement de 3 sources distantes de < 100m)
    b1 = conn.execute("SELECT * FROM bookcases WHERE id = 1;").fetchone()
    assert b1["address"] == "10 Rue Saint-Paul"
    assert b1["photo_url"] == "https://example.com/p1.jpg"
    assert b1["status"] == "pleine"
    assert b1["description"] == "Proche métro"
    assert b1["source_count"] == 3
    sources = json.loads(b1["sources_list"])
    assert "boites_a_livres_fr" in sources
    assert "boitesalivres_com" in sources
    assert "lebouquinfrancais" in sources

    # Vérification de la 2e boîte (Marais, distincte à 333 m)
    b2 = conn.execute("SELECT * FROM bookcases WHERE id = 2;").fetchone()
    assert b2["source_count"] == 1
    assert json.loads(b2["sources_list"]) == ["zonelivre"]
