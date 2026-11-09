# Log Analysis

Projet de Python avancé. Le programme lit les logs SSH d'un serveur (`auth.log`) et affiche des graphiques pour voir qui essaie de se connecter et d'où.

## Lancer le projet

```bash
uv sync
uv run main.py
```

Pour sauvegarder les images sans ouvrir de fenêtre : `uv run main.py --no-show`

Les images sont dans `output/`.

## Ce que fait le programme

1. Il lit tous les fichiers de `data/` (même les `.gz`).
2. Il extrait pour chaque ligne l'IP, l'utilisateur et le résultat (réussi, échoué, utilisateur invalide).
3. Il trouve le pays de chaque IP avec ipinfo.io.
4. Il range tout dans une base sqlite.
5. Il dessine les graphiques avec matplotlib.

## Les graphiques

- tentatives échouées par pays
- connexions réussies par utilisateur
- tentatives échouées avec "Invalid user", par nom d'utilisateur

## Les dossiers

- `data/` : les fichiers de logs
- `ingestion/` et `processing/` : code de départ (je ne les ai pas modifiés)
- `pipeline/` : lecture, parsing et géolocalisation
- `storage/` : la base sqlite
- `serving/` : les graphiques
- `logs/` : les logs de l'application (un fichier par module)

## Problèmes trouvés dans le code de départ

Je n'ai pas modifié `ingestion/` ni `processing/`, donc je les ai contournés dans `pipeline/` :

- `to_rows()` ne lit qu'un seul fichier à cause du `return` dans la boucle
- la regex de `extract_transforme.py` a une erreur de syntaxe, le fichier ne s'importe pas
- `get_location()` n'a pas de timeout ni de gestion d'erreur

## Limites

- ipinfo limite les requêtes sans token, donc certaines IP restent "Unknown". Elles sont retentées au lancement suivant.
- les logs n'ont pas d'année, je l'ai mise à 2026 dans `config.py`
# python.2
