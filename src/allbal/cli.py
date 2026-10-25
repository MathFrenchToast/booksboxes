"""Interface en ligne de commande (CLI) pour AllBAL."""

from __future__ import annotations

import argparse

from allbal.db import DEFAULT_DB_PATH, get_connection, get_stats, init_db
from allbal.deduplicate import DEFAULT_MERGE_RADIUS_METERS, run_deduplication
from allbal.ingest.boitesalivres_com import sync_geographic_zone
from allbal.ingest.lebouquinfrancais import fetch_and_store_lebouquinfrancais
from allbal.ingest.nonmarchand import fetch_and_store_nonmarchand
from allbal.ingest.osm_overpass import fetch_and_store_boites_gpx
from allbal.ingest.zonelivre import fetch_and_store_zonelivre_markers


def cmd_init(args: argparse.Namespace) -> None:
    """Télécharge le socle national en 4 requêtes HTTP uniques et lance la déduplication."""
    conn = get_connection(args.db)
    init_db(conn)

    print("🚀 Initialisation du socle national Fair-Use (4 requêtes HTTP au total)...")

    print("\n[1/4] Téléchargement boites-a-livres.fr (Dump GPX)...")
    c1 = fetch_and_store_boites_gpx(conn, force=args.force)
    print(f"      -> {c1} boîtes enregistrées.")

    print("\n[2/4] Téléchargement zonelivre.fr (Marqueurs globaux)...")
    c2 = fetch_and_store_zonelivre_markers(conn, force=args.force)
    print(f"      -> {c2} marqueurs enregistrés.")

    print("\n[3/4] Téléchargement lebouquinfrancais.fr (Fichier bal.js)...")
    c3 = fetch_and_store_lebouquinfrancais(conn, force=args.force)
    print(f"      -> {c3} marqueurs enregistrés.")

    print("\n[4/4] Téléchargement nonmarchand.org (Page Wiki)...")
    c4 = fetch_and_store_nonmarchand(conn, force=args.force)
    print(f"      -> {c4} boîtes enregistrées.")

    print("\n🔄 Lancement de la déduplication spatiale...")
    dedup_res = run_deduplication(conn, merge_radius_m=args.radius)
    print(
        f"✅ Succès ! {dedup_res['bookcases_created']} boîtes consolidées "
        f"({dedup_res['multi_source_bookcases']} confirmées par plusieurs sources, "
        f"{dedup_res['merged_records']} doublons fusionnés)."
    )


def cmd_sync_zone(args: argparse.Namespace) -> None:
    """Synchronise boitesalivres.com et enrichit zonelivre.fr sur une zone géographique donnée."""
    conn = get_connection(args.db)
    init_db(conn)

    print(
        f"📍 Synchronisation Fair-Use sur ({args.lat}, {args.lon}) dans un rayon de {args.radius_km} km..."
    )
    res = sync_geographic_zone(
        conn, lat=args.lat, lon=args.lon, radius_km=args.radius_km, force=args.force
    )
    print(f"   -> boitesalivres.com : {res['boitesalivres_fetched']} nouvelles fiches.")
    print(f"   -> zonelivre.fr      : {res['zonelivre_enriched']} fiches enrichies avec adresse.")

    if res["boitesalivres_fetched"] > 0 or res["zonelivre_enriched"] > 0:
        print("🔄 Mise à jour de la déduplication spatiale...")
        dedup_res = run_deduplication(conn, merge_radius_m=DEFAULT_MERGE_RADIUS_METERS)
        print(f"✅ Total consolidé : {dedup_res['bookcases_created']} boîtes uniques.")
    else:
        print("✅ Données déjà à jour en cache local (0 requête réseau inutile).")


def cmd_dedup(args: argparse.Namespace) -> None:
    """Lance la déduplication spatiale de tous les enregistrements bruts."""
    conn = get_connection(args.db)
    init_db(conn)
    print(f"🔄 Déduplication spatiale (rayon de fusion : {args.radius} m)...")
    res = run_deduplication(conn, merge_radius_m=args.radius)
    print(f"   - Enregistrements bruts traités : {res['raw_records_processed']}")
    print(f"   - Boîtes consolidées créées     : {res['bookcases_created']}")
    print(f"   - Doublons fusionnés            : {res['merged_records']}")
    print(f"   - Boîtes multi-sources          : {res['multi_source_bookcases']}")


def cmd_stats(args: argparse.Namespace) -> None:
    """Affiche les statistiques de la base de données."""
    conn = get_connection(args.db)
    init_db(conn)
    stats = get_stats(conn)
    print("\n📊 Statistiques de la méta-base AllBAL :")
    print(f"   • Boîtes uniques consolidées   : {stats['total_bookcases']:,}")
    print(f"   • Boîtes multi-sources (revalidées) : {stats['multi_source_bookcases']:,}")
    print(f"   • Boîtes avec photo attestée   : {stats['bookcases_with_photo']:,}")
    print(f"   • Zones géographiques en cache : {stats['cached_zones_count']}")
    print(f"   • Total enregistrements bruts  : {stats['total_raw_records']:,}")
    print("   • Répartition par source :")
    for src, count in sorted(stats["raw_by_source"].items()):
        print(f"      - {src:<20} : {count:,}")
    print()


def cmd_serve(args: argparse.Namespace) -> None:
    """Démarre le serveur web FastAPI."""
    import uvicorn

    print(f"🌐 Lancement du serveur Web AllBAL sur http://{args.host}:{args.port}")
    uvicorn.run("allbal.api:app", host=args.host, port=args.port, reload=args.reload)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="AllBAL - Méta-base et cartographie unifiée des boîtes à livres"
    )
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="Chemin du fichier SQLite")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Commande init
    p_init = subparsers.add_parser("init", help="Initialise le socle national en 4 requêtes")
    p_init.add_argument("--force", action="store_true", help="Force le re-téléchargement")
    p_init.add_argument(
        "--radius",
        type=float,
        default=DEFAULT_MERGE_RADIUS_METERS,
        help="Rayon de fusion en mètres",
    )
    p_init.set_defaults(func=cmd_init)

    # Commande sync-zone
    p_zone = subparsers.add_parser(
        "sync-zone", help="Synchronise une zone géographique (défaut: CP 31540)"
    )
    p_zone.add_argument(
        "--lat",
        type=float,
        default=43.490037,
        help="Latitude du centre (défaut: 43.490037, Saint-Julia)",
    )
    p_zone.add_argument(
        "--lon",
        type=float,
        default=1.898538,
        help="Longitude du centre (défaut: 1.898538, Saint-Julia)",
    )
    p_zone.add_argument("--radius-km", type=float, default=20.0, help="Rayon en km (défaut: 20.0)")
    p_zone.add_argument("--force", action="store_true", help="Ignore le cache de zone")
    p_zone.set_defaults(func=cmd_sync_zone)

    # Commande dedup
    p_dedup = subparsers.add_parser("dedup", help="Relance la déduplication spatiale")
    p_dedup.add_argument(
        "--radius",
        type=float,
        default=DEFAULT_MERGE_RADIUS_METERS,
        help="Rayon de fusion en mètres",
    )
    p_dedup.set_defaults(func=cmd_dedup)

    # Commande stats
    p_stats = subparsers.add_parser("stats", help="Affiche les compteurs et statistiques")
    p_stats.set_defaults(func=cmd_stats)

    # Commande serve
    p_serve = subparsers.add_parser("serve", help="Démarre le serveur FastAPI")
    p_serve.add_argument("--host", default="127.0.0.1", help="Hôte d'écoute")
    p_serve.add_argument("--port", type=int, default=8000, help="Port d'écoute")
    p_serve.add_argument(
        "--reload",
        dest="reload",
        action="store_true",
        default=True,
        help="Rechargement à chaud (défaut: activé)",
    )
    p_serve.add_argument(
        "--no-reload", dest="reload", action="store_false", help="Désactive le rechargement à chaud"
    )
    p_serve.set_defaults(func=cmd_serve)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
