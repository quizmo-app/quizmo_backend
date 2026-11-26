# Quizmo Backend

API backend du projet **Quizmo** développée avec [FastAPI](https://fastapi.tiangolo.com/) et gérée avec [uv](https://docs.astral.sh/uv/).

## Prérequis

- Python 3.11+
- `uv`

## Installation

```bash
uv sync
```

## Lancer le serveur de développement

```bash
uv run fastapi dev app/main.py
# ou
uv run uvicorn app.main:app --reload
```

L'API sera accessible sur `http://localhost:8000` (documentation interactive Swagger sur `http://localhost:8000/docs`).

### Avec le front (enseignant de démonstration)

La connexion (CU1.1) n'existe pas encore : sans jeton ni cookie de session, toutes les routes `/api` répondent
`401 NON_AUTHENTIFIE` (« Session absente ou expirée »). Pour tester avec le front, lancez le serveur avec la
variable `QUIZMO_UTILISATEUR_DEV` : une requête sans en-tête `Authorization` ni cookie est alors traitée comme
cet enseignant.

```bash
# macOS / Linux (sur la même ligne, ou avec export)
QUIZMO_UTILISATEUR_DEV=enseignantA uv run fastapi dev app/main.py
```

```powershell
# Windows (PowerShell)
$env:QUIZMO_UTILISATEUR_DEV="enseignantA"
uv run fastapi dev app/main.py
```

Vérification : `curl http://localhost:8000/api/auth/me` doit renvoyer `{"idEnseignant":"enseignantA"}`.
Si le front reçoit encore un 401, supprimez les cookies `session` / `access_token` de `localhost`
(ils désactivent l'enseignant de démonstration).

La variable n'est lue qu'au démarrage et n'est définie dans aucun fichier du dépôt : ne l'utilisez qu'en
développement (les tests, eux, attendent un 401 sans jeton).

## Lancer les tests

```bash
uv run pytest
```
