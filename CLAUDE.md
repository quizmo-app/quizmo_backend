# CLAUDE.md — Quizmo backend

Backend de **Quizmo** (SAÉ 5.01A, IUT de Montreuil) : un outil type Kahoot où l'enseignant
importe un cours PDF et y insère des quiz entre les pages.

## Stack et commandes

- Python 3.11+, **FastAPI**, gestionnaire de paquets **uv** (pas pip, pas Flask).
- `uv sync` — installer
- `QUIZMO_UTILISATEUR_DEV=enseignantA uv run fastapi dev app/main.py` — serveur sur
  http://localhost:8000 (Swagger : `/docs`)
- `uv run pytest` — tests. **Tous les tests doivent passer avant de dire qu'une tâche est finie.**
- Ajouter une dépendance : `uv add <paquet>` (jamais éditer `pyproject.toml` à la main pour ça).
- Le front (repo `quizmo_frontend`, Vite sur :5173) proxifie `/api/*` vers :8000 → toutes les routes métier sont sous `/api`.
- **Le contrat est dicté par le front déjà écrit** : branche `feature/importer-un-cours-pdf`
  (`src/api/coursApi.ts`, `src/api/http.ts`). En cas de doute, lire ce code plutôt que deviner.

## Architecture (décisions déjà prises)

```
app/
  main.py            # create_app(settings), inclusion des routers
  config.py          # Settings (variables d'env QUIZMO_*)
  database.py        # schéma SQLite, connect(), transaction()
  dependencies.py    # get_settings, get_db, get_pdf_storage, get_current_teacher (JWT)
  exceptions.py      # AppError et ses sous-classes + handlers JSON
  auth/              # JWT (le login LDAP est une autre story)
  courses/           # CourseRepository (SQL), PdfStorage, records
  quizzes/ insertions/ presentations/   # QM-12, QM-13, QM-14 (équipe)
  routers/cours.py   # /api/cours : QM-11 et QM-17
  services/          # logique métier QM-11/QM-17 (cours.py, pdf.py)
  schemas.py         # modèles Pydantic QM-11/QM-17
tests/               # conftest.py : client, settings, db, headers_a/headers_b, seed_*
```

- **Base SQLite** (`app/database.py`, chemin `QUIZMO_DATABASE_PATH`, défaut `data/quizmo.db`).
  Les cours passent par `CourseRepository` (`app/courses/repository.py`), une connexion par
  requête (`Depends`). Écritures dans `with transaction(connexion):` (tout ou rien,
  `PRAGMA foreign_keys = ON`). Pas de dépôt en mémoire.
- **Auth JWT** (`get_current_teacher`, `Authorization: Bearer <jeton>` ou cookie de session ;
  l'identifiant est le `sub`). Le front n'envoie pas encore de jeton : si `QUIZMO_UTILISATEUR_DEV`
  est défini (ex. `enseignantA`), une requête **sans en-tête ni cookie** est traitée comme cet
  enseignant. Sinon (cas des tests) → 401. Dans les tests : fixtures `headers_a` / `headers_b`.
- **Stockage des PDF** : `PdfStorage`, `{QUIZMO_STORAGE_DIR}/{idCours}/v{n}.pdf` (défaut
  `storage/`, un `tmp_path` dans les tests). Jamais exposer le chemin au client. Si la base
  échoue après l'écriture d'un fichier, le fichier est supprimé.
- **Erreurs** : format de l'équipe, via une sous-classe de `AppError` (`app/exceptions.py`) :
  ```json
  { "erreur": "TITRE_MANQUANT", "message": "Veuillez saisir le titre du cours." }
  ```
  (`action` facultatif ; validation FastAPI → 400 `VALIDATION` avec `details`.) Le front affiche
  `message` : en français, destiné à l'enseignant, avec un conseil quand le cahier de recette en
  donne un. Réutiliser un code existant de l'équipe avant d'en créer un.
- **Code de l'équipe** (`app/courses/`, `quizzes/`, `insertions/`, `presentations/`, `database.py`,
  `dependencies.py`) : modifications minimales et additives ; ne pas changer le schéma SQL sans
  accord de l'équipe.
- Nommage : domaine en français (`cours`, `version`, `titre`, `nb_pages`) ; JSON en camelCase
  (`idCours`, `nbPages`) via les alias Pydantic.

## Périmètre du sprint

Les specs à respecter sont dans `docs/specs/` (résumés des cahiers de recette de l'équipe) :
- `QM-11.md` — importer un cours PDF (`POST /api/cours`)
- `QM-17.md` — lister, mettre à jour, structurer, supprimer ses cours

**Le cahier de recette fait foi.** Chaque test de recette réalisable côté back doit avoir un test
pytest équivalent, nommé d'après lui (`test_t04_titre_manquant`). Si la spec est ambiguë ou
contradictoire, on s'arrête et on demande — ne pas trancher en silence.

## Règles de travail (d'après les principes de Karpathy)

1. **Réfléchir avant de coder.** Énoncer ses hypothèses. S'il y a plusieurs interprétations,
   les présenter au lieu d'en choisir une sans le dire. Si quelque chose n'est pas clair, demander.
   Si une approche plus simple existe, le dire.
2. **La simplicité d'abord.** Le minimum de code qui résout le problème demandé. Pas de
   fonctionnalité « au cas où », pas d'abstraction pour un seul usage, pas de config inutile.
3. **Changements chirurgicaux.** Ne toucher que ce que la tâche exige. Ne pas reformater,
   renommer ou « améliorer » le code voisin. Ne nettoyer que ses propres restes.
   Chaque ligne modifiée doit se justifier par la demande.
4. **Exécution guidée par un objectif vérifiable.** Transformer la tâche en critères testables
   (écrire le test qui échoue, puis le faire passer). Pour une tâche en plusieurs étapes,
   annoncer un plan court avec une vérification par étape, et boucler jusqu'à ce qu'elle passe.

## À ne pas faire

- Pas de Flask, pas de SQLAlchemy/PostgreSQL tant que l'équipe ne l'a pas décidé (SQLite brut).
- Pas de commit/push sans qu'on le demande. Une branche par ticket depuis `develop`
  (`feature/qm-17-gestion-cours`), PR vers `develop`, jamais de push direct sur `develop`.
- Ne jamais committer de PDF de test lourds (> 1 Mo) : les générer dans les tests.
