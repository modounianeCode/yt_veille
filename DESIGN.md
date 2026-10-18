# Spec de conception — « YT Veille »

> Outil d'automatisation qui **trouve, classe et archive les meilleures vidéos YouTube par domaine**, avec un service en ligne (web app + API) et des rapports exportables.

Version du document : 1.0 — 18/10/2026
Statut : **à valider avant tout développement**

---

## 1. Objectif & périmètre

### On veut
- Définir des **domaines** (thèmes) : chacun = un ensemble de **mots-clés**.
- Interroger **YouTube Data API v3** régulièrement pour chaque domaine.
- **Classer** les vidéos avec un score multi-signaux (popularité, croissance, pertinence, fraîcheur).
- Consulter les résultats depuis une **interface web**.
- Exporter : **CSV / JSON / Excel** + un **rapport Markdown** daté par domaine.

### On ne fait PAS (pour l'instant)
- ❌ Résumés IA des vidéos → *phase ultérieure*.
- ❌ Transcriptions / sous-titres → *reporté* (l'API officielle ne les donne pas sans OAuth ; on verra via `yt-dlp` plus tard).
- ❌ Comptes multi-utilisateurs → on part sur **usage perso**, avec une porte ouverte vers des comptes.

---

## 2. Décisions issues de l'interview (récapitulatif)

| Sujet | Décision |
|---|---|
| Sens de « domaine » | Thèmes/sujets, définis par **liste de mots-clés** |
| Critère « meilleure » | **Vues + engagement**, **vitesse de croissance**, **pertinence**, **fraîcheur** → score pondéré |
| Source de données | **YouTube Data API v3** (clé API déjà disponible ✅) |
| Sortie | **CSV / JSON / Excel** + **rapport Markdown** |
| Exécution | **Service en ligne** (web app) |
| Hébergement | **Render.com** (recommandé, décision prise) |
| Config domaines | **en base, éditable** — *implémenté via `seed.yml` + commandes CLI* |
| Ampleur | inconnue → dimensionné raisonnablement, **cache API** indispensable |
| Fraîcheur | **fenêtre paramétrable (7 / 30 jours par défaut)** |
| Langue | **toutes langues** |
| Contenu vidéo | **métadonnées seulement** (transcriptions reportées) |
| Base de données | **PostgreSQL (Neon)** en ligne, **SQLite** en local |
| Utilisateurs | **usage perso** au départ |
| Stack | **Python** |
| Public | débutant/intermédiaire → doc et code commentés |
| Démarrage | **POC CLI local d'abord** (phases 1–4) |

### Statut de mise en œuvre

Le **POC CLI (phases 1 à 4)** est implémenté dans le sous-dossier `yt-veille/` :
config, modèles, client YouTube, scoring, collecteur, rapports/exports et CLI.
Les phases 5+ (interface web, planification, déploiement) restent à faire.

---

## 3. Vue d'ensemble de l'architecture

```
                         ┌──────────────────────────────────────────┐
                         │              INTERNET                     │
                         └──────────────────────────────────────────┘
                                          │
                     ┌────────────────────┴────────────────────┐
                     │                                         │
              ┌──────▼───────┐                        ┌─────────▼─────────┐
              │   NAVIGATEUR  │                        │  Clients API /    │
              │  (Interface)  │                        │  cron / scripts   │
              └──────┬───────┘                        └─────────┬─────────┘
                     │ HTTP                                     │ HTTP
                     └──────────────────┬───────────────────────┘
                                        │
                          ┌─────────────▼──────────────┐
                          │   FastAPI (backend Python)  │
                          │  ─ Routes REST /api/*       │
                          │  ─ Sert l'interface HTML    │
                          │  ─ Déclenche la collecte    │
                          └──────┬───────────┬──────────┘
                                 │           │
                ┌────────────────▼──┐   ┌────▼─────────────────────┐
                │  Job de collecte   │   │  Planificateur (cron)    │
                │  (collector)       │   │  ex. toutes les 12 h     │
                │                    │   └──────────────────────────┘
                │  1. mots-clés      │
                │  2. search.list    │
                │  3. videos.list    │
                │  4. scoring        │
                │  5. upsert en base │
                └────────┬───────────┘
                         │
          ┌──────────────┴───────────────┐
          │                              │
   ┌──────▼───────┐              ┌───────▼──────────┐
   │ YouTube Data │              │  PostgreSQL      │
   │ API v3       │              │  (Neon)          │
   └──────────────┘              └──────────────────┘
                                          │
                                 ┌────────▼─────────┐
                                 │  Export          │
                                 │  CSV/JSON/XLSX   │
                                 │  + rapport .md   │
                                 └──────────────────┘
```

**Flux principal (collecte d'un domaine) :**
1. Lire les mots-clés du domaine.
2. Pour chaque mot-clé → `search.list` (filtré sur la fenêtre de fraîcheur).
3. Regrouper les `videoId` → `videos.list` (par lots de 50) pour les statistiques détaillées.
4. Calculer le **score** de chaque vidéo.
5. **Upsert** en base (dédoublonnage par `video_id`).
6. L'interface et les exports lisent la base.

---

## 4. Stack technique recommandée

| Couche | Choix | Pourquoi (niveau débutant/intermédiaire) |
|---|---|---|
| Langage | **Python 3.12** | Déjà installé, écosystème data/API idéal |
| Backend | **FastAPI** | Moderne, rapide, documentation auto (`/docs`), typé |
| Serveur | **Uvicorn** | Standard avec FastAPI |
| Base | **PostgreSQL (Neon)** | Serverless, gratuit pour démarrer, tu en as déjà l'accès |
| Accès DB | **SQLAlchemy 2.0** + **Alembic** (migrations) | ORM lisible, migrations versionnées |
| Appels HTTP | **httpx** (async) | Appels YouTube concurrents = collecte rapide |
| Validation / config | **Pydantic** + **pydantic-settings** | Sécurise les entrées et lit `.env` |
| Interface | **Jinja2 + HTMX + un peu d'Alpine.js** | Pas de gros framework JS, pages simples et réactives |
| Style UI | **Tailwind CSS** (via CDN au début) | Design propre sans chaîne de build |
| Excel | **openpyxl** / **pandas** | Export `.xlsx` facile |
| Tableaux / rapport | **Jinja2** → Markdown | Rapport `.md` daté par domaine |
| Planification | **APScheduler** puis **cron système** | Démarrer simple, fiabiliser ensuite |
| Tests | **pytest** | Standard |
| Conteneurisation | **Docker** + `docker-compose` | Reproductible, facilite le déploiement |
| Qualité | **ruff** (lint) + **black** (format) | Code propre |

### Hébergement — recommandation

Tu es sur un serveur Linux avec Docker. **Deux options classées :**

1. **Recommandé : Render.com** (ou Railway) — le plus simple pour un débutant.
   - Déploiement depuis un dépôt Git, HTTPS automatique, variables d'env via l'interface.
   - Plan gratuit pour tester ; on garde la même image Docker en local et en prod.
2. **Si tu gardes ton serveur :** `docker-compose` + un reverse proxy **Caddy** (HTTPS automatique) + cron pour les collectes.

> 💡 **Conseil clé** : on développe **en Docker** dès le début pour que « ça marche pareil » en local et en ligne. La base reste sur **Neon** dans les deux cas (pas de Postgres à gérer toi-même).

---

## 5. Modèle de données (PostgreSQL)

```
┌────────────────────┐         ┌──────────────────────────┐
│      domains       │         │        keywords          │
├────────────────────┤         ├──────────────────────────┤
│ id (PK)            │◄────────│ id (PK)                  │
│ slug (unique)      │  1   n  │ domain_id (FK)           │
│ name               │         │ term                     │
│ description        │         │ weight (défaut 1.0)      │
│ is_active          │         │ language (nullable)      │
│ created_at         │         │ created_at               │
└─────────┬──────────┘         └──────────────────────────┘
          │ 1
          │
          │ n
┌─────────▼──────────┐         ┌──────────────────────────┐
│      videos        │         │        channels          │
├────────────────────┤         ├──────────────────────────┤
│ id (PK)            │         │ id (PK)  = channelId      │
│ video_id (unique)  │         │ title                    │
│ title              │         │ subscriber_count         │
│ description        │         │ country                  │
│ channel_id (FK)────┼────────►│ updated_at               │
│ published_at       │         └──────────────────────────┘
│ duration_seconds   │
│ view_count         │         ┌──────────────────────────┐
│ like_count         │         │        scores            │
│ comment_count      │         ├──────────────────────────┤
│ thumbnail_url      │         │ id (PK)                  │
│ last_fetched_at    │         │ video_id (FK)            │
│ created_at         │         │ domain_id (FK)           │
└─────────┬──────────┘         │ collected_at             │
          │ 1   n              │ score_total              │
          │                    │ score_views              │
          └────────────────────│ score_engagement         │
                               │ score_growth             │
                               │ score_relevance          │
                               │ score_recency            │
                               │ rank_in_domain           │
                               └──────────────────────────┘

┌──────────────────────────┐     ┌──────────────────────────┐
│    video_domains         │     │      collections         │
├──────────────────────────┤     ├──────────────────────────┤
│ video_id (FK)            │     │ id (PK)                  │
│ domain_id (FK)           │     │ domain_id (FK)           │
│ matched_keywords[]       │     │ started_at               │
│ first_seen_at            │     │ finished_at              │
│ PRIMARY KEY(video,domain)│     │ status                   │
└──────────────────────────┘     │ api_units_used           │
                                 │ videos_found             │
                                 │ error_message            │
                                 └──────────────────────────┘

┌──────────────────────────┐
│   api_quota_usage        │  ← suivi du quota YouTube (10000 unités/jour)
├──────────────────────────┤
│ day (PK)                 │
│ units_used               │
│ requests_count           │
└──────────────────────────┘
```

**Pourquoi une table `scores` datée ?** Pour suivre l'**évolution** d'une vidéo dans le temps → permet de calculer la **vitesse de croissance** (delta de vues entre deux collectes), un de tes 4 critères.

**Dédoublonnage** : une vidéo n'existe qu'une fois (`video_id` unique) même si elle matche plusieurs domaines (`video_domains` gère le lien N–N).

---

## 6. Le cœur : l'algorithme de scoring

Chaque vidéo reçoit **5 sous-scores normalisés entre 0 et 1**, puis un score pondéré.

```
score_total = w_views      × score_views
            + w_engagement × score_engagement
            + w_growth     × score_growth
            + w_relevance  × score_relevance
            + w_recency    × score_recency
```

Poids par défaut (modifiables par domaine et/ou dans les réglages) :

| Signal | Poids par défaut | Calcul |
|---|---|---|
| `score_views` | 0.25 | `log10(views)` normalisé sur le max du domaine |
| `score_engagement` | 0.25 | `(likes + 2×commentaires) / vues`, normalisé |
| `score_growth` | 0.25 | `(vues_now − vues_prev) / heures_écoulées` ; si première collecte → `vues / heures_depuis_publication` |
| `score_relevance` | 0.15 | correspondance mots-clés (titre ×3, description ×1, tags ×2) |
| `score_recency` | 0.10 | décroissance exponentielle : `exp(−âge_jours / τ)`, τ par défaut 7 |

### Normalisation
Pour chaque signal, on ramène les valeurs brutes entre 0 et 1 :

```
normalisé(x) = (x − min) / (max − min)     # min-max sur l'ensemble du domaine
```
> Alternative robuste (recommandée si valeurs extrêmes) : normalisation par **rang percentile**. On implémentera min-max d'abord, avec le percentile en option.

### Détails importants
- **Bruit** : on ignore les vidéos < 24 h pour `score_growth` (trop instables) sauf si assez de vues.
- **Chaines géantes** : option « plafonner / exclure » les chaînes au-delà de N abonnés pour éviter que les hubs écrasent tout.
- **Fenêtre de fraîcheur** : filtre dur (7 / 30 jours) appliqué dès le `search.list` via `publishedAfter`.
- Le **`rank_in_domain`** est stocké à chaque collecte → on peut tracer « la vidéo #1 de la semaine ».

---

## 7. Pipeline de collecte & budget quota API

### Coût des endpoints YouTube (unités de quota)
| Endpoint | Coût | Rôle |
|---|---|---|
| `search.list` | **100** | chercher par mot-clé |
| `videos.list` | **1** | détails de 50 vidéos |
| `channels.list` | **1** | infos de 50 chaînes |

**Quota gratuit par défaut : 10 000 unités/jour.**

### Exemple de budget (run quotidien)
- 10 domaines × 3 mots-clés = **30 `search`** → 30 × 100 = **3 000 unités**
- Détails de ~20 vidéos/domaine → 10 × 1 = **10 unités**
- **Total ≈ 3 010 unités/run** → jusqu'à **~3 runs/jour** dans le quota gratuit. ✅ Confortable.

⚠️ **Le `search.list` est le poste de coût #1.** Stratégies d'optimisation intégrées :
- **Cache** des résultats de recherche (TTL configurable, ex. 6 h) ;
- **Regroupement** des vidéos en lots de 50 pour les détails ;
- **Suivi du quota** en base (`api_quota_usage`) avec alerte à 80 % ;
- Si besoin : **`playlistItems.list`** (1 unité !) sur les uploads de chaînes suivies pour compléter sans exploser le quota.

### Enchaînement
```
pour chaque domaine actif :
  pour chaque mot-clé :
    results ← search.list(q=term, publishedAfter=now−fenêtre, type=video)
    videoIds += results
  détails ← videos.list(ids=videoIds, part=statistics,contentDetails,snippet)
  chaînes ← channels.list(ids=dédupliqués, part=statistics)
  scores  ← calculer_scores(détails, historique)
  upsert(videos, channels, video_domains, scores)
  créer ligne collections(statut=ok, api_units_used=…)
```

---

## 8. API REST (FastAPI)

| Méthode | Route | Description |
|---|---|---|
| `GET` | `/api/domains` | lister les domaines |
| `POST` | `/api/domains` | créer un domaine |
| `PATCH` | `/api/domains/{id}` | modifier (nom, actif, poids) |
| `DELETE` | `/api/domains/{id}` | supprimer |
| `POST` | `/api/domains/{id}/keywords` | ajouter un mot-clé |
| `DELETE` | `/api/keywords/{id}` | supprimer un mot-clé |
| `POST` | `/api/domains/{id}/collect` | **lancer une collecte** (async, renvoie un job id) |
| `GET` | `/api/collections/{job_id}` | statut d'une collecte |
| `GET` | `/api/domains/{id}/videos` | vidéos classées (pagination, tri, filtres) |
| `GET` | `/api/videos/{video_id}` | fiche vidéo + évolution du score |
| `GET` | `/api/reports/{domain}/latest.md` | dernier rapport Markdown |
| `GET` | `/api/export.csv?domain=…` | export CSV |
| `GET` | `/api/export.json?domain=…` | export JSON |
| `GET` | `/api/export.xlsx?domain=…` | export Excel |
| `GET` | `/api/quota` | quota utilisé aujourd'hui |
| `GET` | `/docs` | documentation interactive auto (FastAPI) |

> Toutes les routes d'écriture sont **protégées** dès qu'on ajoutera l'authentification (§12).

---

## 9. Interface web (pages)

1. **Tableau de bord** — quota du jour, dernières collectes, top vidéos tous domaines.
2. **Domaines** — liste, ajout/édition, gestion des mots-clés, bouton « Collecter ».
3. **Résultats d'un domaine** — tableau triable : rang, titre, chaîne, vues, likes, score détaillé, âge, lien. Filtres (période, nb vues mini, langue).
4. **Fiche vidéo** — métadonnées + **graphe d'évolution des vues/score** dans le temps.
5. **Rapports** — historique des rapports Markdown, aperçu et téléchargement.
6. **Réglages** — poids des scores, fenêtre de fraîcheur, TTL de cache, domaines exclus.

L'interface est servie par le même FastAPI (Jinja2 + HTMX) → **un seul service à déployer**.

---

## 10. Gestion des domaines — recommandation

**Recommandé : en base, éditable dans l'interface.** Pourquoi :
- pas besoin de redéployer pour ajouter un domaine ;
- cohérent avec Postgres/Neon déjà choisi ;
- posera les bases pour l'API et le multi-utilisateur.

**Amorçage** : un fichier `seed.yml` fournit 3–5 domaines de départ (ex. `ia`, `dev-web`, `finance`, `sport`, `cuisine`) avec leurs mots-clés, importé au premier lancement.

Exemple de `seed.yml` :
```yaml
domains:
  - slug: ia
    name: Intelligence Artificielle
    keywords: [ "IA générative", "LLM", "GPT", "open source AI", "deep learning" ]
  - slug: dev-web
    name: Développement Web
    keywords: [ "FastAPI", "Python", "JavaScript", "React", "Docker" ]
```

---

## 11. Rapports & exports

**Rapport Markdown** généré par domaine et par collecte, ex. `reports/ia/2026-10-18.md` :

```markdown
# Veille « Intelligence Artificielle » — 18/10/2026

Fenêtre : 7 jours · 42 vidéos analysées · Quota utilisé : 3 010

## 🏆 Top 10

| # | Vidéo | Chaîne | Vues | Engagement | Croissance | Score |
|---|-------|--------|------|------------|------------|-------|
| 1 | [Titre](url) | ChaîneX | 120 400 | 4.2 % | +980/h | 0.91 |
...
```

**Exports** CSV / JSON / XLSX : mêmes colonnes, générés à la demande ou en pièce jointe du rapport.

---

## 12. Sécurité & évolutions

**Au départ (perso) :**
- Clé API et chaîne de connexion DB dans un `.env` (jamais commité).
- URL privée / non référencée.

**Portes laissées ouvertes :**
- Authentification (mot de passe simple puis OAuth Google).
- Multi-utilisateurs (colonne `owner_id` sur `domains`).
- Résumés IA (**LLM**) des vidéos.
- **Transcriptions** via `yt-dlp` (hors API officielle).
- Notifications (email / Telegram / Slack) des nouveautés.

---

## 13. Feuille de route par phases

| Phase | Livrable | Contenu |
|---|---|---|
| **0. Cadrage** | ✅ cette spec | validation des choix |
| **1. Socle** | projet exécutable | structure, Docker, config `.env`, connexion Neon, migrations |
| **2. Collecte** | pipeline fonctionnel | client YouTube, recherche par mots-clés, upsert vidéos/chaînes, suivi quota |
| **3. Scoring** | classement | 5 sous-scores + score pondéré + rang ; tests unitaires |
| **4. API + CLI** | endpoints | routes REST, commande `collect` pour un domaine |
| **5. Interface** | web app | dashboard, domaines, résultats, fiche vidéo |
| **6. Exports & rapports** | livrables | CSV/JSON/XLSX + rapport Markdown daté |
| **7. Planification** | automatisation | APScheduler/cron, alerte quota, historisation des scores |
| **8. Déploiement** | en ligne | image Docker, Render/VPS + Caddy, HTTPS |
| **9. Extensions** | bonus | auth, LLM, transcriptions, notifications |

> On peut **réordonner** : une version « POC CLI en local » (phases 1–4) est idéale pour valider l'idée avant de construire l'interface.

---

## 14. Risques & points d'attention

| Risque | Impact | Mitigation |
|---|---|---|
| **Quota API** épuisé | collecte stoppée | cache, lotissement, suivi quota, `playlistItems` |
| **API officielle ≠ transcriptions** | fonctionnalité reportée | `yt-dlp` plus tard |
| **Chaînes géantes écrasent** le classement | top peu pertinent | plafond/exclusion par abonnés |
| Normalisation **sensible aux extrêmes** | scores biaisés | option percentile |
| **Croissance** nécessite 2 collectes | pas de growth au 1er run | fallback `vues/heure` |
| **CGU YouTube** | usage abusif bloqué | API officielle + quota respecté |

---

## 15. Prochaines étapes

1. **Tu valides / corriges cette spec** (surtout §3 architecture, §6 scoring, §4 hébergement).
2. Je crée l'**arborescence du projet** (phase 1) : Docker, `.env.example`, structure FastAPI, Alembic.
3. J'écris le **client YouTube** + la **commande de collecte** (phase 2).
4. J'implémente le **scoring** avec tests (phase 3).

**Questions à trancher avant la phase 1 :**
- Hébergement : **Render** (simple) ou **ton serveur + Caddy** ?
- Démarrage : **POC CLI local** d'abord, ou **directement l'app web** ?
- Domaines de départ : quel set de 3–5 domaines veux-tu amorcer ?
