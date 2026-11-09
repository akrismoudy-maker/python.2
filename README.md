# Pipeline Log Analyser

Projet de 3ème année (Python avancé). Le programme lit des fichiers `/var/log/auth.log`
d'un serveur SSH, en extrait les tentatives de connexion, les range dans une base sqlite
et dessine trois graphiques pour voir qui attaque le serveur et d'où.

## Objectif

Répondre à trois questions à partir des logs :

1. D'où viennent les tentatives de connexion échouées (par pays) ?
2. Quels utilisateurs se sont vraiment connectés ?
3. Quels noms d'utilisateur inexistants les attaquants essaient-ils ?

## Arborescence

```
log_analysis/
├── main.py                  point d'entrée
├── config.py                chemins et paramètres (data/, logs/, output/, année des logs)
├── logger_config.py         configuration du logging (un fichier par module)
├── data/                    auth.log.1, auth.log.2, auth.log.3.gz, auth.log.4.gz
├── ingestion/raw.py         code de départ (non modifié, voir "Limites connues")
├── processing/              code de départ (non modifié, voir "Limites connues")
├── pipeline/
│   ├── reader.py            lit tous les fichiers de data/, .gz compris
│   ├── parser.py            transforme chaque ligne en événement (regex)
│   ├── geo.py               IP -> pays avec ipinfo.io, cache et gestion d'erreurs
│   └── orchestrator.py      enchaîne lecture, parsing, stockage, géolocalisation
├── storage/event_store.py   base sqlite (classe EventStore)
├── serving/
│   ├── queries.py           requêtes d'agrégation
│   └── dashboard.py         graphiques matplotlib, fonction build_dashboard()
├── logs/                    logs de l'application (généré, ignoré par git)
└── output/                  base events.db et graphiques PNG (généré, ignoré par git)
```

## Installation et lancement

Il faut Python 3.14 (voir `.python-version`) et [uv](https://docs.astral.sh/uv/).

```bash
uv sync                    # crée .venv et installe requests, matplotlib, psycopg2-binary
uv run main.py             # pipeline complet, affiche les graphiques
uv run main.py --no-show   # écrit seulement les PNG (utile sans écran)
uv run main.py --no-geo    # n'appelle pas ipinfo.io (utilise seulement le cache)
```

Options par variables d'environnement :

- `IPINFO_TOKEN` : token ipinfo.io. Sans token la limite gratuite est basse, et ce jeu de
  données contient plus de 1800 IP différentes en échec (voir plus bas).
- `LOG_YEAR` : année des logs (2026 par défaut), car `auth.log` n'écrit pas l'année.

Les graphiques sont écrits dans `output/` : `1_failed_by_country.png`,
`2_success_by_user.png`, `3_invalid_users.png`.

## Les modules

- **`pipeline/reader.py`** : liste les fichiers `auth.log*` de `data/`, les trie du plus
  ancien (`auth.log.4.gz`) au plus récent, et lit chacun (texte ou gzip). Une erreur sur
  un fichier est loguée et les autres fichiers sont quand même lus.
- **`pipeline/parser.py`** : classe `AuthLogParser`. Garde seulement les lignes `sshd`
  utiles et produit des `Event` (date, IP, utilisateur, statut, nombre de tentatives).
- **`pipeline/geo.py`** : classe `GeoLocator`. Donne le pays d'une IP, avec un cache
  dans sqlite pour ne jamais demander deux fois la même IP.
- **`pipeline/orchestrator.py`** : `run_pipeline()` enchaîne tout et retourne un bilan.
- **`storage/event_store.py`** : classe `EventStore` (sqlite3). Tables `events` et `ip_cache`.
- **`serving/queries.py`** : les requêtes SQL d'agrégation.
- **`serving/dashboard.py`** : dessine et sauvegarde les graphiques.
- **`main.py`** : lance le tout, gère les erreurs globales, retourne 0 ou 1.

## Format des logs analysés

Format syslog classique, sans année :

```
May 24 00:04:36 ns sshd[1350968]: Failed password for root from 45.156.87.204 port 40940 ssh2
```

Quatre sortes de messages sont gardées :

| Message | Statut |
|---|---|
| `Accepted password/publickey for <user> from <ip>` | Success |
| `Failed <méthode> for [invalid user] <user> from <ip>` | Failed |
| `Invalid user <user> from <ip>` | Invalid |
| `message repeated N times: [ ... ]` | le message entre crochets, compté N fois |

Le statut Invalid correspond à une ligne "Invalid user" (une par connexion). Le statut
Failed correspond à chaque tentative de mot de passe, y compris pour un utilisateur
inexistant ("Failed password for invalid user admin"). Les deux ne sont donc pas
additionnés : le graphique 1 compte les Failed, le graphique 3 compte les Invalid.

Sur les données fournies : 65 565 lignes, 16 361 tentatives échouées (dont 7 269 cachées
dans des lignes "message repeated"), 3 166 lignes "Invalid user" et 1 connexion réussie.

## Les 3 graphiques

1. **Tentatives échouées par pays** (top 15). Les IP sont géolocalisées avec ipinfo.io. Les
   IP privées (comme 127.0.0.1) sont classées "Private" sans appel réseau. Les IP qu'on n'a
   pas pu localiser sont "Unknown". Ces deux barres sont en gris. Les pays sont affichés
   avec leur code ISO (CN, US, FR...), c'est ce que renvoie ipinfo.
2. **Connexions réussies par utilisateur.** Sur ces logs, un seul utilisateur s'est
   connecté (`adminesisa`, une fois), donc le graphique n'a qu'une barre.
3. **Tentatives "Invalid user"**, en deux panneaux : top 15 des noms d'utilisateur
   essayés (admin, esisa, ubuntu...) et top 15 des IP sources.

## Stratégie de logging

Le module `logger_config.py` fournit `get_logger(__name__, "<fichier>.log")`. Chaque module
a son logger et son fichier dans `logs/`, avec le format
`%(asctime)s|%(levelname)s|%(name)s|%(message)s` et une rotation par taille
(`RotatingFileHandler`, 1 Mo, 5 sauvegardes).

| Fichier | Contenu |
|---|---|
| `ingestion.log` | dossier ou fichier introuvable, permission refusée, gzip corrompu ou tronqué, encodage invalide |
| `processing.log` | lignes non parsables, IP invalide, date invalide, erreurs réseau, timeout et HTTP != 200 sur ipinfo |
| `storage.log` | erreurs sqlite (base verrouillée, contrainte, dossier inaccessible) |
| `serving.log` | erreur d'écriture d'un graphique, requête impossible, dossier de sortie inaccessible |
| `main.log` | déroulement du pipeline et erreurs globales |

Il n'y a aucun `print` et aucun `except: pass`. Si le dossier `logs/` est inutilisable,
le logger écrit sur stderr pour ne pas perdre l'erreur.

## Workflow git

Un commit par module, avec des messages de type `feat(module): ...` :
logging, storage, reader, parser, geo, orchestrator, queries, dashboard, main, puis la doc.
Les dossiers `.venv/`, `__pycache__/`, `logs/` et `output/` sont ignorés. Le dossier `data/`
est versionné pour que le projet soit reproductible.

## Limites connues

Problèmes trouvés dans `ingestion/` et `processing/`. Ces fichiers n'ont volontairement pas
été modifiés : ils sont contournés par les modules de `pipeline/`.

- `ingestion/raw.py` : `to_rows()` fait un `return` dans la boucle, donc elle ne lit que le
  premier fichier du dossier (14 806 lignes lues sur 65 565).
- `ingestion/raw.py` : si le premier fichier n'est pas un `.gz`, `open_type` n'est pas défini
  et le code plante. Si `os.listdir` échoue, `files` n'existe pas non plus.
- `ingestion/raw.py` : les erreurs sont affichées avec `print`, pas loguées. Le dossier est
  lu dans l'ordre de `os.listdir`, qui n'est pas garanti.
- `processing/extract_transforme.py` : la regex contient une apostrophe en trop, le fichier
  a une `SyntaxError` et ne peut pas être importé. Les groupes de la regex sont aussi
  mal imbriqués. De plus `extract_from_row()` affiche le résultat au lieu de le retourner.
- `processing/extract_transforme.py` : les lignes "message repeated N times" ne sont pas
  prévues (elles représentent 7 269 échecs sur 16 361).
- `processing/geo_location.py` : pas de `timeout`, pas de `try/except`, URL avec un double
  slash (`ipinfo.io//<ip>/json`), et un code HTTP autre que 200 donne `None` sans explication.
- `main.py` d'origine appelait `to_rows()` sans argument alors que la fonction en demande un.

Limites de mon propre code :

- L'année des logs n'est pas dans `auth.log`. Elle vient de `config.LOG_YEAR`. Si les logs
  couvrent le passage du 31 décembre au 1er janvier, les dates seront fausses.
- ipinfo.io limite les requêtes sans token. Le jeu de données a environ 1850 IP en échec. En
  cas de limite (HTTP 429) ou de 5 erreurs d'affilée, les appels s'arrêtent et les IP restantes
  sont "Unknown". Les IP les plus actives sont traitées en premier, et les échecs ne sont pas
  mis en cache : relancer plus tard (ou avec `IPINFO_TOKEN`) complète le cache.
- La géolocalisation n'a été testée qu'avec des réponses simulées, pas avec la vraie API.
- La base est reconstruite à chaque lancement (seul le cache des IP est gardé).
- Pas de tests automatiques : la vérification a été faite en comparant avec `grep`.

## Améliorations possibles

- Ajouter des tests unitaires sur le parser.
- Convertir les codes pays en noms complets.
- Utiliser une base de géolocalisation locale (fichier GeoLite2) pour ne plus dépendre d'une API.
- Lire l'année depuis la date de modification du fichier, ou gérer le changement d'année.
- Ajouter un graphique d'évolution des tentatives dans le temps.
- Passer à PostgreSQL (psycopg2 est déjà dans les dépendances) si les volumes grandissent.
