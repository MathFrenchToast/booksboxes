# Architecture Decision Records (ADR) — AllBAL (Méta-BDD Boîtes à Livres)

## Contexte et Besoin
L'objectif du projet **AllBAL** est de :
1. Agréger les différentes bases de données françaises de boîtes à livres (qui sont toutes individuellement incomplètes) au sein d'une **méta-base de données unifiée et dédupliquée**.
2. Permettre de **lister et visualiser sur une carte interactive** toutes les boîtes à livres autour d'une position GPS (« près de moi ») ou dans un périmètre / commune donné(e), en affichant la provenance des sources et les métadonnées fusionnées (adresse, description, état, photos).

---

## ADR-001 : Stockage de la Méta-BDD avec SQLite + Index Spatial R*Tree

- **Statut** : Proposé / Retenu
- **Contexte** : Le volume total brut toutes sources confondues est d'environ 52 000 enregistrements (~19 000 OSM/boites-a-livres.fr + ~17 400 boitesalivres.com + ~9 200 zonelivre.fr + ~6 600 lebouquinfrancais.fr), soit **~25 000 à 30 000 boîtes uniques** après déduplication.
- **Décision** : Utiliser **SQLite 3** (inclus nativement dans Python `sqlite3`) avec son module d'indexation spatiale **R\*Tree** (`VIRTUAL TABLE ... USING rtree`) et une formule Haversine pour le tri par distance exacte.
- **Justification technique** :
  - Zéro infrastructure lourde (pas besoin de serveur PostgreSQL/PostGIS pour 30 000 points), tout tient dans un fichier unique portable (`data/allbal.db`, ~15 Mo).
  - Le module officiel **SQLite R\*Tree** permet des requêtes par boîte englobante (*bounding box*) en moins de 2 ms, idéal pour la recherche par rayon et l'affichage cartographique par viewport.
- **Sources de référence** :
  - Documentation officielle SQLite R\*Tree : [https://www.sqlite.org/rtree.html](https://www.sqlite.org/rtree.html)
  - Documentation SQLite Geopoly : [https://www.sqlite.org/geopoly.html](https://www.sqlite.org/geopoly.html)

---

## ADR-002 : Modèle de données à deux niveaux (`raw_records` vs `bookcases`) et Conflation Spatiale

- **Statut** : Proposé / Retenu
- **Contexte** : Une même boîte à livres physique apparaît souvent dans 2 à 4 bases différentes avec un léger décalage GPS (de 2 à 40 mètres selon que le point a été posé sur la rue, sur le trottoir ou géocodé depuis l'adresse postale) et des attributs complémentaires (ex: photo Wikimedia dans OSM, état `pleine`/`vide` dans `boitesalivres.com`, description précise dans `zonelivre.fr`).
- **Décision** :
  1. **Table `raw_records`** : Stocke les enregistrements bruts tels que moissonnés depuis chaque source (`source_name`, `source_id`, `lat`, `lon`, `name`, `address`, `postcode`, `city`, `description`, `photo_url`, `status`, `raw_json`, `fetched_at`), avec contrainte `UNIQUE(source_name, source_id)`.
  2. **Table `bookcases` (Méta-BDD unifiée)** : Stocke les boîtes dédupliquées avec un identifiant canonique `id`, les coordonnées consolidées (`lat`, `lon`), les métadonnées fusionnées, le score de confiance (`source_count`, liste des `sources`) et une table de liaison `bookcase_sources(bookcase_id, raw_record_id)`.
  3. **Algorithme de déduplication (Conflation)** :
     - Priorité des coordonnées géométriques : `osm` / `boites_a_livres_fr` > `boitesalivres_com` > `zonelivre` > `lebouquinfrancais` > `nonmarchand`.
     - **Seuil de fusion spatiale** : Deux points provenant de sources différentes situés à **moins de 100 mètres** (distance Haversine) sont fusionnés en une seule entité `bookcase` canonique (permettant d'absorber les imprécisions de géocodage au niveau de la rue ou les coordonnées posées manuellement sur smartphone).
     - Enrichissement mutuel : La fiche canonique agrège la meilleure adresse disponible, concatène les descriptions distinctes, conserve la photo (priorité Commons/OSM puis photo communautaire) et l'état de remplissage éventuel (`boitesalivres.com`).

---

## ADR-003 : Stratégie « Fair-Use » à deux vitesses (Dumps 1-requête + Collecte Géographique à la demande)

- **Statut** : Proposé / Retenu
- **Contexte** : Nous souhaitons respecter strictement un **usage équitable (*fair use*)** des serveurs tiers et éviter tout moissonnage massif (pas de pagination sur 93 pages ni de balayage Quadtree national par API).
- **Décision** : Séparer l'ingestion en deux modes complémentaires très économes en requêtes :
  1. **Socle National en 4 requêtes uniques (« Zero-Pagination Dumps »)** — Exécuté une seule fois à l'initialisation (avec cache disque longue durée `TTL = 30 jours`) :
     - `boites-a-livres.fr` : 1 requête (`GET /dumps/boites.gpx`) $\rightarrow$ 19 035 boîtes.
     - `zonelivre.fr` : 1 requête sur l'endpoint léger des marqueurs GeoDirectory (`GET /wp-json/geodir/v2/markers?post_type=gd_place`) $\rightarrow$ 9 217 boîtes (`id`, `lat`, `lon`, `ville`).
     - `lebouquinfrancais.fr` : 1 requête (`GET /js_bal/bal.js`) $\rightarrow$ 6 618 boîtes (`id`, `lat`, `lon`, `ville`).
     - `nonmarchand.org` : 1 requête HTML $\rightarrow$ ~23 boîtes.
     - **Bilan du socle initial : 4 requêtes HTTP au total** pour indexer les coordonnées de ~35 000 points sur toute la France !
  2. **Collecte & Enrichissement ciblés sur une Zone Géographique (`sync_zone(lat, lon, radius_km)`)** :
     - Lorsque l'utilisateur effectue une recherche sur un périmètre donné (via l'interface web ou en CLI `allbal sync-zone --lat ... --lon ... --radius-km 15`) :
       - **Vérification du cache de zone (`fetched_zones`)** : Si la boîte englobante demandée est déjà couverte par une synchronisation datant de moins de 7 jours, **0 requête externe** n'est émise.
       - **`boitesalivres.com` (1 seule requête BBox)** : Appel unique à `GET /api/boxes.php?zoom=10&swlat={s}&swlng={w}&nelat={n}&nelng={e}` sur le périmètre demandé (retourne jusqu'à 500 boîtes locales avec état `pleine`/`vide`/`abimee`, adresse et photo).
       - **`zonelivre.fr` (1 seule requête batch `include`)** : Sélectionne dans SQLite les boîtes `zonelivre` présentes dans le périmètre dont l'adresse détaillée (`street`, `zip`) n'a pas encore été téléchargée, et récupère leurs fiches complètes en **1 seul appel groupé** : `GET /wp-json/geodir/v2/lieu?include=id1,id2,...&per_page=100`.
       - **Relance rapide de la déduplication locale** pour fusionner les nouveautés du périmètre avec le socle existant.
- **Sources de référence** :
  - Documentation officielle GeoDirectory REST API v2 (`/markers` & paramètres `include`) : [https://wpgeodirectory.com/docs-v2/geodirectory/rest-api/](https://wpgeodirectory.com/docs-v2/geodirectory/rest-api/)
  - Documentation FastAPI : [https://fastapi.tiangolo.com/](https://fastapi.tiangolo.com/)
  - Documentation Overpass API : [https://wiki.openstreetmap.org/wiki/Overpass_API](https://wiki.openstreetmap.org/wiki/Overpass_API)

---

## ADR-004 : Visualisation Frontend (Leaflet + MarkerCluster + API Adresse BAN)

- **Statut** : Proposé / Retenu
- **Contexte** : L'interface doit permettre de chercher une adresse/ville ou d'utiliser le GPS du navigateur (« Près de moi »), de choisir un rayon en kilomètres (ex: 1 km, 5 km, 10 km, 25 km), de visualiser le cercle de périmètre sur la carte et de voir la liste triée par distance à côté de la carte.
- **Décision** :
  - **Frontend léger sans étape de build complexe** : HTML5 / CSS moderne (PicoCSS ou CSS Grid responsive) + Vanilla JS servie statiquement par FastAPI (ou ouvrable directement).
  - **Cartographie** : **Leaflet 1.9.4** + **Leaflet.markercluster** pour afficher fluidement des milliers de points avec regroupement dynamique, ainsi qu'un `L.circle` matérialisant le périmètre de recherche.
  - **Géocodage d'adresse / commune** : Utilisation de l'**API Adresse officielle (`api-adresse.data.gouv.fr`)** pour l'autocomplétion de ville, code postal ou rue en France.
- **Sources de référence** :
  - Documentation officielle Leaflet : [https://leafletjs.com/reference.html](https://leafletjs.com/reference.html)
  - Documentation officielle API Adresse (BAN `data.gouv.fr`) : [https://adresse.data.gouv.fr/api-doc/adresse](https://adresse.data.gouv.fr/api-doc/adresse)

---

## ADR-005 : Sécurité, CI/CD (GHCR) et Déploiement K3s avec PVC `local-path` & Gateway API

- **Statut** : Retenu & Déployé (`https://bal.perso.frenchtoast.dev`)
- **Contexte** : L'application doit être déployée sur le cluster K3s de `vm-hostinger` derrière le sous-domaine `bal.perso.frenchtoast.dev` protégé par une authentification HTTP BasicAuth (équivalent `.htaccess`), tout en garantissant la persistance de la base SQLite (`~15 Mo`) lors des redémarrages de Pod ou de l'hôte.
- **Décision** :
  1. **Durcissement Sécurité (Code & Dépendances)** :
     - Parsing XML sécurisé contre les attaques XXE/Billion Laughs via `defusedxml.ElementTree`.
     - Validation stricte anti-SSRF / anti-Open-Redirect (`is_safe_http_url`, `is_allowed_scrape_url`) sur le proxy de résolution des photos (`GET /api/photo/{bookcase_id}`) et assainissement anti-XSS côté client (`sanitizeUrl`).
     - Pipeline GitHub Actions (`.github/workflows/ci.yml`) bloquant la publication d'image si l'un des contrôles échoue : `ruff check`, `ruff format --check`, `bandit` (SAST), `pip-audit` (SCA) ou `pytest` (15 tests).
  2. **Image Conteneur Multi-Stage (`Dockerfile`)** :
     - Build reproductible avec `uv sync --frozen --no-dev` sur `python:3.12-slim`, exécuté sous un utilisateur non-root (`uid/gid 10001`).
     - Script d'entrée `docker-entrypoint.sh` initialisant automatiquement la base SQLite (`allbal.cli init` + `sync-zone` sur Saint-Julia `31540` rayon `20 km`) uniquement si le fichier `/app/data/allbal.db` est absent sur le volume persistant.
  3. **Hébergement SQLite sur K3s (`k8s/deployment.yaml`)** :
     - **Stockage** : `PersistentVolumeClaim` (`allbal-data-pvc`, `200Mi`, `ReadWriteOnce`, `storageClassName: local-path`) attaché à un `Deployment` mono-réplica (`replicas: 1`) configuré en `strategy.type: Recreate` pour éviter tout verrouillage concurrent (`SQLITE_BUSY` / multi-attach) sur le mode WAL de SQLite.
     - **Évolution future identifiée** : La base étant déjà configurée en mode `PRAGMA journal_mode=WAL;`, l'ajout d'un sidecar **Litestream** (`litestream restore` en `initContainer` + `litestream replicate` vers S3) pourra être activé sans aucune modification du code Python si une réplication externe hors-nœud devient nécessaire.
     - **Exposition & Sécurité Edge** : Utilisation de la **Kubernetes Gateway API** (`Gateway` `allbal-gateway` dans `traefik` + `HTTPRoute` `allbal-route`), certificat TLS Let's Encrypt géré par `cert-manager` (`ClusterIssuer` `letsencrypt-allbal-prod` en HTTP-01 `gatewayHTTPRoute`), et `Middleware` Traefik `basicAuth` (`allbal-basic-auth` lié au secret `allbal-basic-auth-secret`).
- **Sources de référence** :
  - Documentation K3s Storage (`local-path`) : [https://docs.k3s.io/storage](https://docs.k3s.io/storage)
  - Documentation Traefik BasicAuth Middleware : [https://doc.traefik.io/traefik/middlewares/http/basicauth/](https://doc.traefik.io/traefik/middlewares/http/basicauth/)
  - Documentation Astral `uv` Docker Integration : [https://docs.astral.sh/uv/guides/integration/docker/](https://docs.astral.sh/uv/guides/integration/docker/)
  - Documentation Litestream on Kubernetes : [https://litestream.io/guides/kubernetes/](https://litestream.io/guides/kubernetes/)

---

## Structure du projet

```text
allbal/
├── README.md
├── pyproject.toml               # Dépendances Python & configuration ruff / bandit / pytest
├── uv.lock                      # Lockfile reproductible uv
├── Dockerfile                   # Build multi-stage non-root (python:3.12-slim + uv)
├── docker-entrypoint.sh         # Auto-init SQLite sur PVC vierge puis lancement Uvicorn
├── .dockerignore
├── .gitignore
├── .github/
│   └── workflows/
│       └── ci.yml               # CI (ruff, bandit, pip-audit, pytest) + Push GHCR
├── k8s/
│   ├── argocd-application.yaml  # Application GitOps Argo CD (auto-sync sur main)
│   ├── kustomization.yaml       # Entrée Kustomize lue par Argo CD
│   └── deployment.yaml          # Manifeste K3s (Namespace, PVC, Deployment, Service, Middleware, Gateway, HTTPRoute, Cert-Manager)
├── doc/
│   ├── sources_analysis.md      # Audit technique des 7 sites et endpoints découverts
│   ├── adr.md                   # Décisions d'architecture (ce document)
│   └── tasks.md                 # Plan de réalisation et suivi des étapes
├── data/                        # Dossier local (ignoré par git)
│   ├── raw/                     # Cache local des fichiers téléchargés (GPX, JSON, JS, HTML)
│   └── allbal.db                # Base SQLite locale (~15 Mo : raw_records + bookcases + rtree)
├── src/
│   └── allbal/
│       ├── __init__.py
│       ├── db.py                # Schéma SQLite WAL, R*Tree, requêtes spatiales Haversine
│       ├── models.py            # Modèles de données normalisés
│       ├── ingest/              # Connecteurs Fair-Use par source
│       │   ├── __init__.py
│       │   ├── base.py          # Client HTTP avec cache disque et User-Agent explicite
│       │   ├── osm_overpass.py  # Connecteur GPX boites-a-livres.fr (defusedxml)
│       │   ├── zonelivre.py     # Connecteur WP GeoDirectory REST API (/markers & batch /lieu)
│       │   ├── boitesalivres_com.py # Connecteur BBox boitesalivres.com + orchestrateur sync_geographic_zone
│       │   ├── lebouquinfrancais.py # Connecteur parser JS bal.js
│       │   └── nonmarchand.py   # Connecteur parser HTML PmWiki
│       ├── deduplicate.py       # Algorithme de conflation spatiale (rayon 100 m, R*Tree + Haversine)
│       ├── cli.py               # CLI: `init`, `sync-zone`, `dedup`, `stats`, `serve` (auto free port >= 8000)
│       ├── api.py               # FastAPI (/api/bookcases, /api/bookcases/bbox, /api/stats, /api/export.geojson, /api/photo/{id})
│       └── static/              # Interface Web (Carte Leaflet + MarkerCluster + Liste + Modal photo)
│           ├── index.html
│           ├── style.css
│           └── app.js
└── tests/
    ├── test_api_integration.py  # Tests API, fichiers statiques, sécurité URL et sélection de port libre
    ├── test_db_spatial.py       # Tests Haversine, R*Tree, cache de zone et statistiques
    ├── test_deduplicate.py      # Tests de fusion spatiale à 100 m
    └── test_parsers.py          # Tests unitaires des 5 parseurs sur fixtures
```
