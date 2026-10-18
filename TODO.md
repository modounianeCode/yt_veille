# TODO / Feuille de route — YT Veille

> Fichier de mémoire du projet. Il liste ce qui reste à faire, **pourquoi**, et **où** toucher
> dans le code. À tenir à jour : cocher / supprimer au fur et à mesure.
>
> Dernière mise à jour : 18/10/2026 · HEAD `1cbdc12` (UI « produit fini »)

---

## 1. En attente d'une décision utilisateur (priorités)

Les trois leviers ci-dessous ont été identifiés mais **volontairement pas implémentés** :
il faut choisir l'ordre. Aucun n'est bloquant — le service tourne correctement sans eux.

### 1.1 Filtrer les Shorts — *le plus rentable*

**Problème mesuré** : sur le domaine `islam`, 23 vidéos sur 124 sont des Shorts ; sur `dev-web`
la majorité du top 15 est en `#shorts`. Un Short de 11 s n'est pas de la veille utile et
fausse la perception du classement (il fausse peu le score, mais beaucoup la confiance).

**Piste** : une durée minimale (ex. 121 s, seuil historique de YouTube) appliquée **avant**
le scoring, sur le même modèle que le filtre de pertinence existant.

- Où : `yt_veille/collector.py` → à côté de `is_relevant()` dans `collect_domain()`
- Le champ existe déjà : `Video.duration_seconds` (pas de migration nécessaire)
- Réglage : nouvelle variable `MIN_DURATION_SECONDS` dans `config.py` + `.env.example`
  + `render.yaml`, exposée dans `Settings` (même schéma que `REQUIRE_KEYWORD_MATCH`)
- Penser à un pendant pour la purge rétroactive : `purge_irrelevant()` sait déjà faire
  ce genre de nettoyage à coût quota nul → l'étendre ou ajouter `yt-veille purge --shorts`
- Tests : `tests/test_collector.py` (une vidéo de 30 s doit être écartée, une de 10 min gardée)

**Attention** : ne pas casser les domaines où le format court est légitime (aucun aujourd'hui,
mais à vérifier avec l'utilisateur avant d'activer par défaut).

### 1.2 Restreindre la collecte par langue

**Problème** : `finance` et `ia` remontent des vidéos coréennes / turques, car
`search.list` est appelé sans `relevanceLanguage`.

- Où : `yt_veille/youtube.py`, méthode de recherche → ajouter `relevanceLanguage`
- ⚠️ **Contrainte forte** : une langue **par domaine** exigerait une nouvelle colonne
  (`Domain.relevance_language`) — impossible sur la base Neon en ligne (voir §4).
  Deux options :
  - **globale** : un réglage `RELEVANCE_LANGUAGE` dans `Settings` (simple, suffisant si
    l'utilisateur veut surtout « français + anglais ») ;
  - **par domaine** : contourner l'absence de migration en réutilisant une colonne
    existante, ou accepter de recréer la table. À éviter tant que possible.
- Vérifier l'effet sur le quota : aucun surcoût (même appel `search.list`)

### 1.3 Mots-clés exclus

**Problème** : « highlights » (sport), « réaction » / « REACT » (dev-web) ramènent du bruit.
Le filtre `REQUIRE_KEYWORD_MATCH` ne peut rien y faire : il exige une correspondance
**positive**, il n'exclut rien.

- ⚠️ Même contrainte que §1.2 : distinguer un mot-clé « à inclure » d'un mot-clé « à exclure »
  demanderait une colonne (`Keyword.is_excluded`) → impossible sur Neon.
- **Astuce retenue** : préfixer le terme dans la liste des mots-clés, par ex. `-réaction`,
  `-highlights`. Le signe `-` est déjà interdit par la validation YouTube et ne perturbe
  pas les recherches. Implémentation : dans `collect_domain()`, séparer les termes en deux
  listes (`include` / `exclude`) et rejeter une vidéo dont le titre/tags/description contient
  un terme exclu.
- Où : `yt_veille/scoring.py` (`is_relevant()` → ajouter `matches_excluded()`),
  `yt_veille/collector.py`
- Tests : `tests/test_scoring.py`

---

## 2. Idées en réserve (non demandées, à proposer un jour)

- **Mode sombre** sur l'interface (Tailwind `class` strategy + bascule dans l'en-tête).
- **Recherche globale** en haut de page (chercher un titre dans tous les domaines).
- **Comparaison de domaines** : voir quels thèmes montent (vues cumulées par collecte).
- **Notification** quand une vidéo dépasse un score seuil (e-mail ou webhook).
- **Transcriptions** (`captions.download`) : écarté pour l'instant — lourd en quota et
  en traitement, à rouvrir seulement si le besoin « résumé automatique » apparaît.
- **Export pour un sous-ensemble filtré** : aujourd'hui l'export ignore les filtres de
  la page (vues minimum, tri) et sort toujours le classement complet.

---

## 3. Points de vigilance opérationnels (rien à coder)

- **GitHub désactive les workflows planifiés après 60 jours** sans activité sur le dépôt.
  Si le site semble figé : onglet *Actions* → « Re-enable » sur « Collecte YT Veille ».
- **`CRON_TOKEN`** n'existe que dans le dashboard Render (Environment) — il n'est pas dans
  le `.env` local. Pour le lire : Render → service → Environment.
- **Quota** : 10 000 unités/jour. Une collecte complète des 5 domaines ≈ 2 630 unités
  (`search.list` = 100 unités/requête). Le garde-fou marque les domaines en `skipped` au
  lieu d'échouer quand le quota manque — c'est normal, pas une erreur.
- **Le `.env` local pointe sur Neon** : les commandes CLI lancées en local modifient la
  base de production. À garder en tête avant tout test destructif.
- **Déclenchement manuel** : GitHub → *Actions* → « Collecte YT Veille » → *Run workflow*.

---

## 4. Contrainte structurante à ne pas oublier

**Aucune migration de schéma n'est possible sur la base Neon en ligne.**
Le projet n'utilise pas Alembic : `init_db()` fait un `create_all()`, qui **crée** les tables
manquantes mais n'ajoute **jamais** de colonne à une table existante.

Conséquence : toute nouvelle information doit se loger dans
1. une variable de configuration (`Settings` / `.env` / `render.yaml`), **ou**
2. une colonne déjà existante (quitte à détourner son sens), **ou**
3. une convention sur une valeur existante (d'où le préfixe `-` de §1.3).

Les domaines ont déjà été migrés « à la main » pour les poids `w_*` — c'est le précédent.
Si un vrai besoin de schéma apparaît un jour (multi-utilisateur, langue par domaine), la
bonne réponse est d'introduire Alembic **et** de faire la migration une fois, proprement.

---

## 5. Historique récent (pour situer le contexte)

| Commit | Objet |
|---|---|
| `1cbdc12` | UI « produit fini » : icônes SVG, accueil, pages d'erreur |
| `9aef151` | Jeton cron via en-tête HTTP `X-Cron-Token` |
| `77d3ce3` | Collecte automatique via GitHub Actions |
| `8a79246` | Planificateur interne désactivé (`SCHEDULE_ENABLED=false`) |
| `e5b3587` | Corrige le mot-clé `React` → `React JS` + `React tutoriel` |
| `112c955` | Filtre de pertinence + poids pertinence 0.15 → 0.30 |
| `fbdc903` | Ajout du domaine « islam » |
| `cda9481` | Refonte de l'interface (Tailwind, HTMX, vignettes) |
