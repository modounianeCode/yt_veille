# YT Veille — POC CLI

Outil d'automatisation qui **trouve, classe et archive les meilleures vidéos
YouTube par domaine** (thème + mots-clés), à partir de la **YouTube Data API v3**.

> 📄 La conception complète est dans [`DESIGN.md`](DESIGN.md).
> État actuel : **phases 1 à 5 et 7** faites (CLI, collecte, scoring, **interface
> web**, **planification**). Reste : déploiement en ligne.

---

## Ce que fait cette version

1. **Domaines** = un thème + une liste de mots-clés (4 domaines fournis dans `seed.yml`).
2. **Collecte** : pour chaque mot-clé → recherche YouTube, puis récupération des statistiques.
3. **Scoring** : chaque vidéo reçoit un score pondéré sur 5 signaux
   (vues, engagement, croissance, pertinence, fraîcheur).
4. **Stockage** : SQLite en local (ou PostgreSQL/Neon en ligne).
5. **Sorties** : classement en console, rapport **Markdown** daté, exports **CSV / JSON / XLSX**.

---

## Prérequis

- Python 3.11 ou plus récent.
- Une **clé YouTube Data API v3**.
  → Google Cloud Console → activer « YouTube Data API v3 » → créer une clé d'API.

---

## Installation

```bash
cd yt-veille

# 1. Environnement virtuel
python3 -m venv .venv
source .venv/bin/activate

# 2. Installation (le pilote PostgreSQL est inclus)
pip install -e .

# 3. Configuration
cp .env.example .env
#   → ouvre .env et colle ta clé dans YOUTUBE_API_KEY
```

---

## Démarrage rapide

```bash
# Crée les tables
yt-veille init-db

# Importer les 4 domaines de départ (IA, dev web, finance, sport)
yt-veille seed

# Lancer une première collecte (tous les domaines actifs)
yt-veille collect

# Voir le classement d'un domaine
yt-veille top --domain ia --limit 15

# Générer le rapport Markdown
yt-veille report --domain ia

# Exporter en Excel
yt-veille export --domain ia --format xlsx

# Vérifier le quota YouTube consommé aujourd'hui
yt-veille quota

# Lancer l'interface web → http://127.0.0.1:8000
yt-veille serve
```

### Interface web

`yt-veille serve` ouvre un service FastAPI qui propose :

- **Tableau de bord** : statistiques, quota du jour, top 3 par domaine, dernières collectes.
- **Domaines** : création, activation/désactivation, ajout/suppression de mots-clés, bouton **Collecter**.
- **Résultats d'un domaine** : tableau filtrable (vues minimum, tri par score/vues/engagement/récence) + exports.
- **Fiche vidéo** : métadonnées et **graphique d'évolution** du score et des vues.
- **Rapports** : génération et lecture des rapports Markdown.
- **API JSON** sous `/api/*` et documentation interactive sur `/docs`.

### Collectes automatiques (planification)

Deux options, au choix :

```bash
# A) Processus dédié (recommandé en production)
yt-veille worker

# B) Intégré au serveur web : passer SCHEDULE_ENABLED=true dans .env
```

Réglages dans `.env` :

```dotenv
SCHEDULE_ENABLED=true
SCHEDULE_TIMES=06:00,18:00      # heures de collecte, séparées par des virgules
SCHEDULE_TIMEZONE=UTC
```

Un **garde-fou de quota** empêche de lancer une collecte qui dépasserait les
10 000 unités/jour : le domaine est alors marqué « skipped ».

---

## Toutes les commandes

| Commande | Rôle |
|---|---|
| `init-db` | Crée les tables |
| `seed [--file seed.yml]` | Importe les domaines/mots-clés |
| `domains` | Liste les domaines |
| `add-domain --slug --name` | Crée un domaine |
| `add-keyword --domain --term` | Ajoute un mot-clé |
| `collect [--domain SLUG] [--days N] [--max N] [--order X]` | Lance une collecte |
| `top --domain SLUG [--limit N]` | Affiche le classement |
| `report --domain SLUG [--limit N]` | Génère le rapport Markdown |
| `export --domain SLUG [--format csv\|json\|xlsx] [--out PATH]` | Exporte les données |
| `quota` | Quota API utilisé aujourd'hui |
| `serve [--host H --port P]` | Lance l'interface web |
| `worker` | Lance le planificateur de collectes |

---

## Le scoring en un coup d'œil

```
score_total = 0.25·vues + 0.25·engagement + 0.25·croissance + 0.15·pertinence + 0.10·fraîcheur
```

- **vues** : échelle logarithmique (log10).
- **engagement** : `(likes + 2×commentaires) / vues`.
- **croissance** : `Δvues / heures` depuis la collecte précédente
  (ou `vues / âge` à la première collecte).
- **pertinence** : mot-clé dans le titre (=3), les tags (=2), la description (=1).
- **fraîcheur** : décroissance exponentielle `exp(−âge_jours / τ)`.

Tous les signaux sont normalisés (min-max) **par domaine** pour être comparables.
Les poids sont réglables par domaine (colonnes `w_*` de la table `domains`).

---

## Base de données

- **Local** : SQLite par défaut → `yt_veille.db` (aucune installation).
- **En ligne (Neon)** : renseigne `DATABASE_URL` dans `.env` :
  ```
  DATABASE_URL=postgresql+psycopg://user:pass@host.neon.tech/neondb?sslmode=require
  ```

---

## Docker

```bash
docker compose run --rm yt-veille yt-veille collect
docker compose run --rm yt-veille yt-veille top --domain ia
```

L'image sert l'interface web par défaut (`yt-veille serve`), exposée sur le port 8000
(ou `$PORT` fourni par l'hébergeur).

---

## Déploiement en ligne (Render + Neon)

Le dépôt contient tout le nécessaire : `render.yaml`, `Dockerfile`, `.dockerignore`.

1. **Pousser le code sur GitHub** (dépôt `modounianeCode/yt_veille`).
2. Sur **Render** → **New → Blueprint** → sélectionner le dépôt.
   Render lit `render.yaml` et crée le service web (région Francfort, même que Neon).
3. Renseigner les **secrets** demandés par Render :
   - `DATABASE_URL` → chaîne Neon : `postgresql+psycopg://…@…neon.tech/neondb?sslmode=require`
   - `YOUTUBE_API_KEY` → ta clé YouTube
4. Déployer. Le conteneur crée les tables, importe les domaines, puis démarre le serveur.
   Santé : `GET /health`.

### Option cron externe

Sur le plan gratuit, le service s'endort après inactivité et le planificateur interne
ne tourne donc pas en continu. Pour des collectes fiables, utilise un cron externe
(gratuit) qui appelle :

```
GET https://<ton-service>.onrender.com/api/cron/collect?token=<CRON_TOKEN>
```

`CRON_TOKEN` est généré par Render (`generateValue: true`) et consultable dans le
tableau de bord. Tant que le jeton est vide, l'endpoint renvoie `403`.

---

## Tests

```bash
pip install -e ".[dev]"
pytest -q
```

---

## Budget quota YouTube

Le quota gratuit est de **10 000 unités/jour**. `search.list` coûte **100 unités**
par appel : ~30 recherches = 3 000 unités par run complet. Le compteur est suivi
dans la table `api_quota_usage` et affiché par `yt-veille quota`.

---

## Prochaines étapes (voir DESIGN.md §13)

Interface web FastAPI · planification (cron/APScheduler) · exports XLSX enrichis ·
résumés IA · transcriptions (`yt-dlp`) · notifications · déploiement Render.
