# AllBAL — Méta-BDD et Cartographie des Boîtes à Livres en France

Je souhaite pouvoir lister toutes les Boites à Livres près de moi ou dans un périmètre donné.
Il y a de nombreuses cartes en ligne, mais elles sont toutes incomplètes ; ce projet crée donc une **méta-base de données unifiée et dédupliquée** avec une visualisation cartographique interactive, dans le strict respect d'un usage équitable (*Fair-Use*) des serveurs tiers.

## Sources inventoriées et agrégées

Voici les sites inventoriés pour constituer la méta-base coopérative :
- [Base de données coopérative des boites à livres de France](https://www.boites-a-livres.fr/) *(OpenStreetMap / Wikimedia Commons)*
- [Carte interactive des boites à livres en France](https://lebouquinfrancais.fr/boites-a-livres.php)
- [Les boites à livres par département, ville - Forum OSM France](https://forum.openstreetmap.fr/t/les-boites-a-livres-par-departement-ville/20093)
- [Boîtes à Livres — Carte Communautaire France](https://boitesalivres.com/)
- [Nonmarchand.org | EspacesDeGratuite / Carte participative des boîtes à lire](https://nonmarchand.org/pmwiki/EspacesDeGratuite/RechercheCarteBo%C3%AEte%C3%80Livres)
- [Accueil - Boîte à Livres by Zonelivre](https://boite.a.livres.zonelivre.fr/)
- [Trouver une boîte à livres par ville et région | ReadTrip](https://readtrip.fr/rechercher-une-boite-a-livres/)

*(Voir l'audit technique détaillé dans [`doc/sources_analysis.md`](doc/sources_analysis.md) et les choix d'architecture dans [`doc/adr.md`](doc/adr.md)).*

---

## Lancer le projet en local

### 1. Prérequis et installation

Le projet requiert **Python 3.11+** et utilise [`uv`](https://docs.astral.sh/uv/) (ou `pip` standard).

Avec **uv** (recommandé) :
```bash
uv sync --all-extras
```

Ou avec un environnement virtuel standard (`venv` + `pip`) :
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 2. Initialiser la méta-base de données (Socle national Fair-Use)

Lors du premier lancement, initialisez la base SQLite locale (`data/allbal.db`). Cette commande récupère les dumps nationaux en **4 requêtes HTTP uniques** (~35 000 enregistrements bruts) et applique la déduplication spatiale (fusion des boîtes distantes de moins de 100 m) :

```bash
uv run python -m allbal.cli init
```

*(Optionnel)* Pour enrichir une zone géographique spécifique auprès des API paginées (`boitesalivres.com` et `zonelivre.fr`) — par défaut centré sur Saint-Julia (31540) dans un rayon de 20 km :
```bash
uv run python -m allbal.cli sync-zone
# Ou sur des coordonnées personnalisées :
uv run python -m allbal.cli sync-zone --lat 43.6045 --lon 1.4440 --radius-km 15
```

### 3. Démarrer le serveur Web et la carte interactive

Lancez le serveur local FastAPI / Uvicorn (avec rechargement automatique `--reload` activé par défaut) :

```bash
uv run python -m allbal.cli serve
```

Ouvrez ensuite votre navigateur sur :
👉 **[http://127.0.0.1:8000](http://127.0.0.1:8000)** (ou [http://localhost:8000](http://localhost:8000))

Options disponibles pour `serve` :
- `--host 0.0.0.0` : écouter sur toutes les interfaces réseau
- `--port 8080` : changer le port d'écoute (défaut : `8000`)
- `--no-reload` : désactiver le rechargement automatique à chaud

---

## Autres commandes utiles

- **Afficher les statistiques de la base consolidée** :
  ```bash
  uv run python -m allbal.cli stats
  ```
- **Relancer la déduplication spatiale** (avec un rayon personnalisé en mètres, défaut `100.0`) :
  ```bash
  uv run python -m allbal.cli dedup --radius 100
  ```
- **Exécuter la suite de tests unitaires et d'intégration** :
  ```bash
  uv run pytest
  ```
- **Vérifier le formatage, le linter et la sécurité (identique à la pipeline CI GitHub Actions)** :
  ```bash
  uv run ruff check .
  uv run ruff format --check .
  uv run bandit -c pyproject.toml -r src/
  uv run pip-audit
  ```

