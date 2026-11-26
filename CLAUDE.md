# CLAUDE.md — Quizmo backend

Backend de **Quizmo** (SAÉ 5.01A, IUT de Montreuil) : un outil type Kahoot où l'enseignant
importe un cours PDF et y insère des quiz entre les pages.

## Stack et commandes

- Python 3.11+, **FastAPI**, gestionnaire de paquets **uv** (pas pip, pas Flask).
- `uv sync` — installer
- `uv run fastapi dev app/main.py` — serveur sur http://localhost:8000 (Swagger : `/docs`)
- `uv run pytest` — tests. **Tous les tests doivent passer avant de dire qu'une tâche est finie.**
- Ajouter une dépendance : `uv add <paquet>` (jamais éditer `pyproject.toml` à la main pour ça).
- Le front (repo `quizmo_frontend`, Vite sur :5173) proxifie `/api/*` vers :8000 → toutes les routes métier sont sous `/api`.
- **Le contrat est dicté par le front déjà écrit** : branche `feature/importer-un-cours-pdf`
  (`src/api/coursApi.ts`, `src/api/http.ts`). En cas de doute, lire ce code plutôt que deviner.

## Architecture (décisions déjà prises)

```
app/
  main.py            # create_app(), inclusion des routers
  routers/           # une route = un fichier par ressource (cours.py, ...)
  services/          # logique métier, sans FastAPI (pdf.py, stockage.py, ...)
  repositories/      # accès aux données derrière une interface
  schemas.py         # modèles Pydantic des requêtes/réponses
  errors.py          # ErreurMetier + handler JSON unique
  auth_bouchon.py    # dépendance get_current_user
tests/
```

- **Pas de base de données pour l'instant.** Les données passent par une interface
  `CoursRepository` (Protocol). Implémentation actuelle : `InMemoryCoursRepository`.
  Une implémentation SQL (SQLAlchemy + PostgreSQL) viendra plus tard : les routers et services
  ne doivent **jamais** dépendre d'une implémentation concrète, seulement de l'interface,
  injectée avec `Depends`.
- **Auth bouchonnée.** `get_current_user` lit `Authorization: Bearer <login>` et renvoie
  l'enseignant correspondant (`enseignantA`, `enseignantB` existent en dur). Le front n'envoie
  pas encore d'en-tête (seulement `credentials: 'include'`) : si la variable d'env
  `QUIZMO_UTILISATEUR_DEV` est définie (ex. `enseignantA`), une requête sans en-tête est traitée
  comme cet enseignant. Sinon (cas des tests) → 401. Le vrai LDAP/JWT remplacera uniquement cette fonction.
- **Stockage des PDF** : `{STORAGE_DIR}/{idCours}/v{n}.pdf`, `STORAGE_DIR` lu dans l'env
  (défaut `./data/pdf`, un `tmp_path` dans les tests). Jamais exposer le chemin au client.
- **Erreurs** : toujours ce format **à plat** (c'est ce que lit le front, `errorBody.message`),
  via `ErreurMetier(status, code, message)` :
  ```json
  { "code": "TITRE_MANQUANT", "message": "Veuillez saisir le titre du cours." }
  ```
  Les erreurs de validation FastAPI (422 par défaut) doivent aussi passer par ce format.
  Messages en français, destinés à l'enseignant, avec un conseil quand le cahier de recette en donne un.
- Nommage : domaine en français (`cours`, `version`, `titre`, `nb_pages`) ; JSON en camelCase
  (`idCours`, `nbPages`) via les alias Pydantic.

## Périmètre du sprint

Les specs à respecter sont dans `docs/specs/` (résumés des cahiers de recette de l'équipe) :
- `QM-11.md` — importer un cours PDF (`POST /api/cours`)
- `QM-17.md` — lister, mettre à jour, structurer, supprimer ses cours

**Le cahier de recette fait foi.** Chaque test de recette réalisable sans BDD doit avoir un test
pytest équivalent, nommé d'après lui (`test_t04_titre_manquant`). Si la spec est ambiguë ou
contradictoire, on s'arrête et on demande — ne pas trancher en silence.

## Règles de travail (d'après les principes de Karpathy)

1. **Réfléchir avant de coder.** Énoncer ses hypothèses. S'il y a plusieurs interprétations,
   les présenter au lieu d'en choisir une sans le dire. Si quelque chose n'est pas clair, demander.
   Si une approche plus simple existe, le dire.
2. **La simplicité d'abord.** Le minimum de code qui résout le problème demandé. Pas de
   fonctionnalité « au cas où », pas d'abstraction pour un seul usage, pas de config inutile.
   (Exception assumée : l'interface repository ci-dessus.)
3. **Changements chirurgicaux.** Ne toucher que ce que la tâche exige. Ne pas reformater,
   renommer ou « améliorer » le code voisin. Ne nettoyer que ses propres restes.
   Chaque ligne modifiée doit se justifier par la demande.
4. **Exécution guidée par un objectif vérifiable.** Transformer la tâche en critères testables
   (écrire le test qui échoue, puis le faire passer). Pour une tâche en plusieurs étapes,
   annoncer un plan court avec une vérification par étape, et boucler jusqu'à ce qu'elle passe.

## À ne pas faire

- Pas de Flask, pas de SQLAlchemy/PostgreSQL tant que l'équipe ne l'a pas décidé.
- Pas de commit/push sans qu'on le demande. Une branche par ticket : `QM-11-import-cours`.
- Ne jamais committer de PDF de test lourds (> 1 Mo) : les générer dans les tests.
