# Confessio - Claude Code Guide

## Commands

Each command below has a `mise run` shortcut (defined in `mise.toml`). Both forms work.

### Run server
```bash
python manage.py runserver
# or: mise run server
```

### Run background tasks worker
```bash
python manage.py process_tasks --sleep 1
# or: mise run worker
```

### Lint
```bash
flake8 .
# or: mise run lint
```

### Test
```bash
python -m unittest discover -s scheduling/tests -s crawling/tests
# or: mise run test
```

### Check module dependencies
```bash
python scripts/check_dependencies.py
# or: mise run check-deps
```

### Run all pre-commit checks (lint + deps + test)
```bash
mise run check
```

### Translations (front app only)
```bash
# Extract strings
python manage.py makemessages -l fr
# Compile
python manage.py compilemessages
# or both: mise run translations
```

### V2 encoder (developer-only, manual)

The V2 temporal/confession classifiers run on a fine-tuned camembert-large `Encoder`
(sentence → 1024-d embedding) shared by per-target heads (`Classifier`). The encoder is trained
in **dev** and promoted on **prod** by hand (it needs ~5-6 GB, too heavy for the nightly cron).
The two V2 heads are trained **only** jointly with the encoder (`train_encoder`) and registered by
`promote_encoder` — there is **no** nightly V2 head retrain: the encoder is label-fine-tuned on
those sentences, so retraining/evaluating a head alone on the stored embeddings leaks (the embedding
already encodes the label). Nightly only runs `reclassify_sentences` (re-embed/relabel) and
`find_sentence_outliers` — no model training at all. Requires `HF_TOKEN` (write access to the
private HF repo).

Dev/prod split: `train_encoder` runs in dev on a prod-DB dump and writes only to HF (no DB);
`promote_encoder` runs on prod (or locally to test) and registers the encoder from HF into the DB.

```bash
# 1. (DEV) Fine-tune encoder + heads on the local prod-dump; push body + tokenizer + meta.json
#    (with the head weights) to the HF repo. NO database writes.
python manage.py train_encoder            # --repo-id confessio-labs/pruning-v2-encoder

# 1b. If the push failed (training is staged locally), retry without retraining:
python manage.py push_encoder             # --repo-id ...

# 2. (PROD) Register from HF into THIS DB and flip PROD: creates the Encoder + the two heads,
#    significance-checks vs the current PROD encoder, sets PROD. Does NOT re-embed.
python manage.py promote_encoder --repo-id confessio-labs/pruning-v2-encoder --revision <sha>
#    (-f to force; restart inference processes afterwards)
```

Re-embedding is **lazy**: when the encoder changes, each sentence's `encoder_embedding` is
recomputed on-the-fly the next time it's classified, and persisted in bulk by the nightly
`reclassify_sentences`.

Dependencies: inference needs only `torch` + `transformers` (the `ml` dependency group, installed
in dev and prod). `scikit-learn` is used solely by `train_encoder.py`, so it lives in the `dev`
group and `encoder_service.train_and_stage_encoder` imports the training module lazily to keep it
off the prod import path.

## Architecture

Modular Django monorepo with 7 apps. Each app has its own models, views, services, and management commands.

### Apps

| App | Role |
|-----|------|
| `core` | Base models, settings, utilities, OTEL middleware |
| `registry` | Ecclesial entities: Diocese, Parish, Church, Website |
| `crawling` | Web crawling: Scraping, Crawling logs, moderation |
| `fetching` | External data sources (OClocher API integration) |
| `scheduling` | Confession schedule pipeline: pruning, parsing, matching, indexing |
| `attaching` | Image uploads and LLM-based image parsing |
| `front` | Public-facing views + django-ninja REST API |


### Key models

- `registry.Diocese` - Catholic diocese
- `registry.Parish` - Parish (belongs to Diocese, optionally has Website)
- `registry.Church` - Physical church with PostGIS PointField location (SRID 4326)
- `registry.Website` - Parish website to crawl
- `crawling.Scraping` - Crawled page (URL + website)
- `crawling.Crawling` - Crawl session metadata
- `scheduling.Scheduling` - Full pipeline state for a website (built -> pruned -> parsed -> matched -> indexed)
- `scheduling.Pruning` - Pruned HTML snippet containing schedule data
- `attaching.Image` - Uploaded image with LLM-extracted HTML

### Scheduling pipeline

`Scheduling.Status` progression:
1. `built` - resources collected (scrapings, images, OClocher data)
2. `pruned` - HTML pruned to confession-relevant snippets
3. `parsed` - LLM parses time/day schedules from snippets
4. `matched` - schedules matched to churches
5. `indexed` - final schedules indexed for search

### REST API

django-ninja API defined in `front/api.py`, mounted in `front/urls.py`. Namespace: `main_api`.

## Tech stack

- **Django 5.2** with Python 3.13
- **PostgreSQL** with **PostGIS** (spatial queries) and **pgvector** (embeddings)
- **django-ninja** for REST API (Pydantic schemas)
- **django-simple-history** for model versioning (all key models have `HistoricalRecords`)
- **django-background-tasks** for async workers
- **fructose** / **openai** for LLM calls
- **torch** + **transformers** for ML models (fine-tuned camembert-large encoder + per-target heads)
- **uv** for dependency management (`pyproject.toml`)

## Code style

- Max line length: 100 characters (enforced by flake8)

## Project structure conventions

- Models use `TimeStampMixin` (from `core.models.base_models`) for `created_at`/`updated_at`
- Moderation models inherit `ModerationMixin` (from `registry.models`)
- Business logic lives in `*/services/` subdirectories
- Pipeline workflows live in `*/workflows/` subdirectories
- Management commands in `*/management/commands/` — one-shot migrations prefixed with `one_shot__`
- Tests in `*/tests/` — run with standard `manage.py test`
- Translation strings only in `front` app (`front/locale/fr/`)
