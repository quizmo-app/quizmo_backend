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

## Lancer les tests

```bash
uv run pytest
```
