#!/bin/sh
set -e

DB_FILE="${ALLBAL_DB_PATH:-/app/data/allbal.db}"

# Si la base n'existe pas encore sur le PVC (premier déploiement), on l'initialise
if [ ! -s "$DB_FILE" ]; then
    echo "📦 Base SQLite absente sur le PVC ($DB_FILE) : initialisation du socle national Fair-Use..."
    python -m allbal.cli --db "$DB_FILE" init
    echo "📍 Enrichissement initial de la zone par défaut (Saint-Julia 31540, rayon 20 km)..."
    python -m allbal.cli --db "$DB_FILE" sync-zone || true
else
    echo "✅ Base SQLite existante détectée sur le PVC ($DB_FILE)."
fi

exec uvicorn allbal.api:app --host 0.0.0.0 --port "${PORT:-8000}"
