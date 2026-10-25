# Analyse technique des sources de données — Projet AllBAL

Ce document synthétise l'audit technique des 7 sites listés dans le fichier [`README.md`](../README.md), ainsi que de la base amont OpenStreetMap (OSM).

---

## 1. Synthèse comparative des 7 sites audités

| # | Site | Nature de la source | Volume constaté (Oct. 2026) | Méthode d'extraction / Endpoint découvert | Licence / Politique | Pertinence pour la Méta-BDD |
|---|---|---|---|---|---|---|
| **1** | **[boites-a-livres.fr](https://www.boites-a-livres.fr/)** | Vitrine OpenStreetMap (`amenity=public_bookcase` & `give_box`) + photos Wikimedia Commons + géocodage inverse BAN | **19 035** boîtes (10 341 photos) | Export direct GPX quotidien : `https://www.boites-a-livres.fr/dumps/boites.gpx` (2,49 Mo) ou requête directe Overpass API | **ODbL** (OpenStreetMap) | **Très haute (Socle primaire)** — Miroir propre d'OSM France enrichi d'adresses BAN |
| **2** | **[lebouquinfrancais.fr](https://lebouquinfrancais.fr/boites-a-livres.php)** | Base propriétaire communautaire (SAS Scriptage) | **6 618** boîtes (France + Belgique/Suisse/DOM) | Fichier JS statique contenant toutes les coordonnées : `https://lebouquinfrancais.fr/js_bal/bal.js` (`var villes = {...}`) + `POST https://lebouquinfrancais.fr/action_bal.php` (`idSelect=<id>`) pour le détail | Propriétaire (site commercial de livres d'occasion) | **Haute** — Contient des boîtes signalées par des lecteurs absentes d'OSM ; extraction instantanée en 1 requête HTTP |
| **3** | **[Forum OSM France (sujet #20093)](https://forum.openstreetmap.fr/t/les-boites-a-livres-par-departement-ville/20093)** | Fil de discussion communautaire (créateur de `boites-a-livres.fr`, Sylvain Machefert / `@symac`) | N/A (discussion) | Documente la requête Overpass officielle (`https://overpass-turbo.eu/s/1G7r`) et les autres sites existants | N/A | **Documentaire** — Ne stocke pas de données propres, explique l'écosystème OSM |
| **4** | **[boitesalivres.com](https://boitesalivres.com/)** | Carte communautaire (Le Carré Numérique) fusionnant OSM + signalements utilisateurs + état (`pleine`, `vide`, `abimee`) + commentaires | **17 414** boîtes | API JSON par bounding-box (**1 requête par zone géographique**) : `GET https://boitesalivres.com/api/boxes.php?zoom=10&swlat=...&swlng=...&nelat=...&nelng=...` (jusqu'à 500 boîtes/zone) | **ODbL** (mentionnée sur `/a-propos`) | **Très haute** — Possède des métadonnées uniques (état de la boîte, description précise, photos locales) sous licence libre ODbL |
| **5** | **[nonmarchand.org (GratiRézo)](https://nonmarchand.org/pmwiki/EspacesDeGratuite/RechercheCarteBo%C3%AEte%C3%80Livres)** | Wiki PmWiki associatif + calque OSM | **~23** fiches propres dans le wiki HTML (+ calque `osm_bal_france`) | Parsing HTML de la balise `<dl class='map'>` directement sur la page PmWiki (**1 seule requête**) | Contenu libre / associatif | **Faible / Marginale** — Seulement ~20 boîtes propres (souvent anciennes, 2013–2019), mais facile à parser en 1 requête |
| **6** | **[boite.a.livres.zonelivre.fr](https://boite.a.livres.zonelivre.fr/)** | Annuaire WordPress + plugin GeoDirectory porté par l'Association Zonelivre | **9 217** boîtes | **Dump léger en 1 requête** : `GET /wp-json/geodir/v2/markers?post_type=gd_place` (9 217 coordonnées) + **Enrichissement par zone en 1 requête** : `GET /wp-json/geodir/v2/lieu?include=id1,id2,...&per_page=100` | Associative | **Très haute** — 9 217 fiches accessibles sans pagination lourde grâce à `/markers` + enrichissement local ciblé |
| **7** | **[readtrip.fr](https://readtrip.fr/rechercher-une-boite-a-livres/)** | Site WordPress (thème MyListing / Elementor) | **1 seule** boîte à livres réelle (`found_posts: 1`) | API AJAX MyListing : `GET https://readtrip.fr/?mylisting-ajax=1&action=get_listings&listing_type=boite-a-livres` (1 seule fiche à Wambrechies : `post-11618`) | Propriétaire | **Nulle / Négligeable** — Coquille quasi vide (1 seule boîte référencée malgré l'annonce de la page) |

---

## 2. Analyse détaillée par source et format des données (Politique Fair-Use)

### Source 0 (Amont de référence) : OpenStreetMap via Overpass API
- **Documentation officielle** :
  - Tag OSM : [https://wiki.openstreetmap.org/wiki/FR:Tag:amenity%3Dpublic_bookcase](https://wiki.openstreetmap.org/wiki/FR:Tag:amenity%3Dpublic_bookcase)
  - Tag complémentaire : [https://wiki.openstreetmap.org/wiki/FR:Tag:amenity%3Dgive_box](https://wiki.openstreetmap.org/wiki/FR:Tag:amenity%3Dgive_box)
  - Overpass API : [https://wiki.openstreetmap.org/wiki/Overpass_API](https://wiki.openstreetmap.org/wiki/Overpass_API)
- **Intérêt** : Interroger directement Overpass API (`https://overpass-api.de/api/interpreter`) sur une zone géographique permet de récupérer les tags bruts complets d'OSM (`name`, `description`, `operator`, `opening_hours`, `wheelchair`, `capacity`, `wikimedia_commons`, `image`, `panoramax`, `check_date`, `@timestamp`).

### Source 1 : `boites-a-livres.fr` (Dump complet — 1 requête)
- **Endpoints directs découverts** :
  - `GET https://www.boites-a-livres.fr/dumps/boites.gpx` (2,49 Mo) : 19 035 points GPX (`<wpt lat="..." lon="..."> <name>Boite - X</name> <desc>Adresse BAN</desc> </wpt>`). Ne contient **pas** les URLs des images dans les balises GPX.
  - `GET https://www.boites-a-livres.fr/dumps/libraries.json` (644 Ko) : Dump JSON compact des 19 035 boîtes sous forme de tableau `[lat, lon, id, has_image]`. Le 4e champ `0` ou `1` indique immédiatement si la boîte possède ou non une photo !
- **Récupération des images (CC-BY-SA)** :
  1. **Convention d'URL directe du CDN local** : `https://www.boites-a-livres.fr/image/{osm_node_id}.jpg` (redimensionnée en 400x533).
  2. **Origine Wikimedia Commons & OpenStreetMap** : Les images proviennent des tags OpenStreetMap `wikimedia_commons = "File:Nom_du_fichier.jpg"` (ou `image=*`).
     - URL de l'image originale ou redimensionnée via Wikimedia Commons :
       `https://commons.wikimedia.org/wiki/Special:FilePath/{Nom_du_fichier}?width=600`
     - URL de la page de métadonnées Commons (licence CC-BY-SA et auteur) :
       `https://commons.wikimedia.org/wiki/{Nom_du_fichier}`
  3. **Fiche individuelle** : `GET https://www.boites-a-livres.fr/s/{id}` redirige vers la page `/ville/.../boite-{id}` qui contient les balises `<meta property="og:image" content="..." />` et `<a itemprop="photo" href="https://commons.wikimedia.org/wiki/File:...">` avec le texte `Crédit photo : CC BY-SA 4.0 {Auteur}`.
- **Politique Fair-Use** : Fichier d'export officiel prévu pour le téléchargement complet (2,49 Mo GPX ou 644 Ko JSON). Mis en cache localement dans `data/raw/` (rafraîchissement hebdomadaire ou mensuel uniquement).

### Source 2 : `lebouquinfrancais.fr` (Fichier statique — 1 requête)
- **Endpoint direct** : `https://lebouquinfrancais.fr/js_bal/bal.js` (environ 489 Ko).
- **Format** : Contient une variable globale JavaScript `var villes = {"5":{"lat":44.0415188,"lon":4.098213,"id":5,"city":"Ribaute les tavernes"}, ...};` regroupant **6 618 entrées**.
- **Politique Fair-Use** : Le fichier `bal.js` est chargé en une seule requête par tout visiteur de leur carte. On le met en cache localement (`data/raw/lebouquinfrancais_bal.js`). On **ne boucle jamais** sur `POST /action_bal.php` : les détails HTML d'une fiche ne sont demandés qu'au clic explicite de l'utilisateur sur une boîte spécifique (et mis en cache en base).

### Source 4 : `boitesalivres.com` (API par Zone Géographique — 1 requête par zone)
- **Endpoint découvert** :
  - `GET https://boitesalivres.com/api/boxes.php?zoom=10&swlat=<min_lat>&swlng=<min_lon>&nelat=<max_lat>&nelng=<max_lon>`
- **Format JSON retourné** :
  ```json
  {
    "success": true,
    "total": 17414,
    "data": [
      {
        "id": 2,
        "adresse": "3 Rue du Faubourg Saint-Antoine",
        "cp": "75011",
        "ville": "Paris",
        "description": "Petite cabane bleue, côté pharmacie",
        "latitude": 48.8534,
        "longitude": 2.3741,
        "photo_url": null,
        "etat": "pleine"
      }
    ]
  }
  ```
- **Politique Fair-Use (Zéro moissonnage national)** :
  - L'endpoint `/api/boxes.php` plafonne à **500 résultats par appel** (ce qui couvre largement un périmètre de recherche local de 5 à 30 km ou un département).
  - Plutôt que d'aspirer toute la France, on interroge cette API **uniquement sur la zone géographique (bounding box) demandée par l'utilisateur** (1 seule requête HTTP) et on mémorise la zone téléchargée dans une table SQLite `fetched_zones` (TTL de 7 jours) pour ne plus émettre aucune requête lors des recherches suivantes dans ce secteur.

### Source 5 : `nonmarchand.org` (Page unique — 1 requête)
- **Endpoint** : `https://nonmarchand.org/pmwiki/EspacesDeGratuite/RechercheCarteBo%C3%AEte%C3%80Livres`
- **Format** : Liste HTML `<dl class='map'><dt> lat/lon </dt><dd> <a href='...'>Titre</a> </dd></dl>`.
- **Volume** : ~23 points spécifiques extraits en 1 seule requête HTTP mise en cache.

### Source 6 : `boite.a.livres.zonelivre.fr` (Dump léger `/markers` en 1 requête + Enrichissement par Zone)
- **Documentation officielle GeoDirectory REST API v2** : [https://wpgeodirectory.com/docs-v2/geodirectory/rest-api/](https://wpgeodirectory.com/docs-v2/geodirectory/rest-api/)
- **1. Endpoint global léger (1 seule requête pour toute la France)** :
  - `GET https://boite.a.livres.zonelivre.fr/wp-json/geodir/v2/markers?post_type=gd_place`
  - Retourne instantanément les **9 217 marqueurs** sous forme condensée :
    ```json
    {
      "total": 9217,
      "items": [
        { "m": "17", "lt": "48.38934664755921", "ln": "-4.501846432685853", "t": "Brest", "i": 39 }
      ]
    }
    ```
    *(où `m` = ID de la fiche, `lt` = latitude, `ln` = longitude, `t` = ville/titre)*.
- **2. Enrichissement ciblé sur la zone géographique (1 seule requête groupée)** :
  - Grâce aux coordonnées déjà connues en SQLite via `/markers`, lorsqu'on recherche dans un périmètre donné, on identifie localement les IDs `m` de `zonelivre` situés dans ce périmètre qui n'ont pas encore leur adresse complète, et on les récupère en **1 seule requête batch** via le paramètre standard WordPress `include` :
  - `GET https://boite.a.livres.zonelivre.fr/wp-json/geodir/v2/lieu?include=17,18,39&per_page=100`
  - Format JSON détaillé retourné :
    ```json
    {
      "id": 33597,
      "title": { "raw": "Festieux", "rendered": "Festieux" },
      "slug": "festieux",
      "latitude": "49.523634400303",
      "longitude": "3.7560099476678",
      "street": "21ter Grande Rue, 02840 Festieux",
      "city": "Festieux",
      "region": "Hauts-de-France",
      "country": "France",
      "zip": "02840"
    }
    ```
- **Bilan Fair-Use** : **1 seule requête initiale** au lieu de 93 pages, puis **1 requête groupée uniquement sur votre zone géographique** !

### Source 7 : `readtrip.fr`
- **Constat** : Le sitemap (`job_listing-sitemap.xml` et `job_listing-sitemap2.xml`) et l'endpoint AJAX `https://readtrip.fr/?mylisting-ajax=1&action=get_listings&listing_type=boite-a-livres` montrent qu'il n'y a qu'**une seule** boîte à livres enregistrée (`21 Rue Obert 59118 Wambrechies`).
- **Décision** : Inutile de développer un scraper complexe pour 1 seul point ; il peut être ignoré ou importé statiquement.

### Autres sources découvertes via le fil OSM France et `boites-a-livres.fr/a-propos` (Opportunités d'extension Phase 2)
- `https://www.boite-a-lire.com/` (RecycLivre, ~9 600 boîtes)
- `https://delivrez.fr/maps/` (~40 000 points incluant boîtes à dons et grainothèques)
