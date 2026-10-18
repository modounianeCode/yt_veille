# YT Veille — POC CLI

Outil d'automatisation qui **trouve, classe et archive les meilleures vidéos
YouTube par domaine** (thème + mots-clés), à partir de la **YouTube Data API v3**.

> 📄 La conception complète est dans [`DESIGN.md`](DESIGN.md).
> Cette première version est un **POC en ligne de commande** (phases 1 à 4 de la
> feuille de route). L'interface web viendra ensuite.

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

# 2. Installation (avec le pilote PostgreSQL optionnel)
pip install -e .
# ou, si tu veux aussi écrire vers Neon :
# pip install -e ".[postgres]"

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
```

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
