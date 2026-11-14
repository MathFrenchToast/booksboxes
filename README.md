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

Ouvrez ensuite votre navigateur sur l'URL affichée dans le terminal :
👉 **[http://127.0.0.1:8000](http://127.0.0.1:8000)** (si le port `8000` est déjà occupé, le serveur bascule automatiquement sur le premier port libre supérieur, ex: `8001`).

Options disponibles pour `serve` :
- `--host 0.0.0.0` : écouter sur toutes les interfaces réseau
- `--port 8080` : changer le port de départ souhaité (`>= 8000`, défaut : `8000`)
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

---

## Déploiement en production sur K3s (`bal.perso.frenchtoast.dev`)

L'application est déployée sur le cluster K3s de `vm-hostinger` à l'adresse :
👉 **[https://bal.perso.frenchtoast.dev](https://bal.perso.frenchtoast.dev)** *(protégée par BasicAuth Traefik + TLS Let's Encrypt via Cert-Manager et Kubernetes Gateway API)*.

La base SQLite consolidée ne pesant que **15 Mo** (~24 400 boîtes uniques + index R\*Tree), le déploiement utilise une image conteneur légère non-root publiée automatiquement par GitHub Actions sur `ghcr.io/mathfrenchtoast/booksboxes:latest` et un `PersistentVolumeClaim` K3s (`local-path` de `200Mi` en mode `ReadWriteOnce` avec stratégie `Recreate`).

### 1. Créer le namespace, copier le `ghcr-secret` existant et créer le secret BasicAuth (`.htaccess`)
Sur le cluster K3s (`vm-hostinger`) :
```bash
kubectl create namespace allbal --dry-run=client -o yaml | kubectl apply -f -

# Copier le pull secret GHCR déjà présent dans le namespace sf2 (ou t3d)
kubectl get secret ghcr-secret -n sf2 -o json \
  | jq 'del(.metadata.resourceVersion,.metadata.uid,.metadata.creationTimestamp,.metadata.annotations,.metadata.ownerReferences) | .metadata.namespace="allbal"' \
  | kubectl apply -f -

# Générer ou mettre à jour le Secret BasicAuth (format bcrypt) lu par le Middleware Traefik
kubectl -n allbal create secret generic allbal-basic-auth-secret \
  --from-literal=users="$(htpasswd -nbB mathieu 'VOTRE_MOT_DE_PASSE')" \
  --dry-run=client -o yaml | kubectl apply -f -
```

### 2. Activer le déploiement GitOps via Argo CD (recommandé)
Le dépôt étant public (`https://github.com/MathFrenchToast/booksboxes.git`), Argo CD sur `vm-hostinger` synchronise automatiquement le dossier [`k8s/`](k8s/) (`kustomization.yaml` $\rightarrow$ `deployment.yaml`) avec `selfHeal: true` et `prune: true` :
```bash
kubectl apply -f k8s/argocd-application.yaml
```
*(Ou en application directe sans Argo CD : `kubectl apply -k k8s/`).*

- **Premier démarrage automatique** : si `/app/data/allbal.db` est absent sur le PVC, [`docker-entrypoint.sh`](docker-entrypoint.sh) initialise automatiquement le socle national (`allbal.cli init`) et enrichit la zone 31540 (`allbal.cli sync-zone`).
- **Mettre à jour vers la dernière image publiée sur GHCR** :
  ```bash
  kubectl -n allbal rollout restart deployment/allbal
  ```
- **Alternative (copie directe d'une base locale `data/allbal.db` vers le PVC du Pod)** :
  ```bash
  POD=$(kubectl -n allbal get pod -l app=allbal -o jsonpath='{.items[0].metadata.name}')
  kubectl -n allbal cp data/allbal.db "$POD:/app/data/allbal.db"
  kubectl -n allbal rollout restart deployment/allbal
  ```


