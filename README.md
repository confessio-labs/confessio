# Confessio
A search engine for confession hours by scraping parish websites.

This is the codebase of the [confessio.fr](https://confessio.fr) project,
and its [API](https://confessio.fr/api/docs).

Please open an issue if you find a bug, or if you have any question or suggestion.
You can also reach us through the [contact form](https://confessio.fr/contact).
Also, you might want to check our [status page](https://status.confessio.fr/).

---
## 📄 Licenses

- The **source code** is released under the **GNU GPL v3 License** ([see LICENSE](./LICENSE)).  
  → This is a strong copyleft license that allows reuse and modification, but requires that any derivative work also be released under the GPL and remain open-source.

- The **data provided through the API** is released under the **ODbL v1.0 license** ([see LICENSE_ODBL](./LICENSE_ODBL)).  
  → This license allows free use, sharing, and adaptation of the database, provided you attribute the source and share any improvements under the same terms.

Please make sure to **credit the source** when using the data, and if possible, add a “Report an error” link near each displayed piece of data, including Confessio brand name and its logo. We encourage you to **get in touch with the maintainer** to ensure proper usage and collaboration.

---
## 🧡 Sponsors
We'd like to thank our sponsor [Hozana](https://hozana.org/) for their continuous support.

![Hozana](static/assets/img/logo/hozana-logo-medium.png)

---
# Project architecture

The software architecture is inspired by the [Modular Monolith](https://www.milanjovanovic.tech/blog/what-is-a-modular-monolith) architecture, which consists in structuring the codebase in independent modules (Django apps) that communicate through well defined interfaces (e.g. signals, or direct function calls). This allows for better maintainability and scalability of the codebase.

## Project apps structure
The project is structured in a modular way, with the following Django apps:
- `registry`: manages the registry of churches, parishes and dioceses.
- `crawling`: manages the crawling of parish websites to extract text about confession hours.
- `attaching`: manages the upload and OCR of images of schedules.
- `fetching`: manages the fetching of external sources (e.g. OClocher).
- `scheduling`: gathers the outcome of crawling, attaching and fetching, to produce schedules.
- `front`: is responsible for the broadcasting of schedules. It contains the frontend code (Django templates, views, etc) and the API (Django REST Framework).
- `core`: contains shared code and utilities.

Other directories:
- `ansible`: contains ansible playbooks and configuration for deploying to production.
- `static`: contains static files (CSS, JS, images, etc).

## Django app directory structure
The django apps have this file structure:
```
app_name/
├── __init__.py
├── admin.py  # django admin configuration
├── apps.py  # django app configuration
├── forms/  # django forms
├── management/
│   └── commands/  # custom django commands
├── migrations/  # django models migrations
├── models.py  # django objects definitions
├── public_service.py  # methods that use Django objects, and that can be used by other apps
├── public_workflow.py  # methods that do not use Django objects, and that can be used by other apps
├── services/  # methods that use Django objects
├── signals.py  # django signals (models pre-hooks and post-hooks)
├── tasks.py  # entrypoint of the background worker
├── templates/  # django templates
├── templatetags/  # django template tags
├── tests/  # unit tests (without django loading)
├── urls.py  # django urls configuration
├── utils/  # utilitary methods that do not use Django objects, and that can be used by other apps
├── views/  # django views
├── workflows/  # business-related methods that do not use Django objects
```

The `front` app has these additional files and directories:
```front/
├── api.py  # django rest framework api views
├── front_api.py  # django rest framework front api views
├── locale/  # translations
```
Also, the `core` app contains the different settings files.

## App dependencies rules

Here are the rules about the dependencies between apps:
- an app can use objects from another app, but in read-only mode.
- an app can call a function in public_workflow or public_service of another app, but no other methods.
- an app can use function in another app `utils` directory.
- a utils or workflow method can not call a service method, and can not use Django objects.
- any part of `core` app can be used by any other app.
- the import of background.tasks must be done exclusively in `tasks.py` files.

A good dependency visualization tool is [tach](https://github.com/tach-org/tach): `tach init` (at first time) and then `tach show --web`.

---

# Dev environment

## Quick start with mise (recommended)

The project ships a [`mise`](https://mise.jdx.dev) config (`mise.toml`) that pins the tool versions
(Python 3.13.11 + uv), loads `.env`, and defines task shortcuts. Once mise is
[installed and activated](https://mise.jdx.dev/getting-started.html) in your shell:

```shell
mise trust      # required once: mise.toml loads .env and defines tasks
mise install    # install pinned Python + uv
mise run setup  # install dev dependencies (uv sync --group dev)
```

Then use the task shortcuts:

```shell
mise run server        # python manage.py runserver
mise run worker        # python manage.py process_tasks --sleep 1
mise run lint          # flake8 .
mise run test          # unit tests
mise run check-deps    # module dependency check (tach)
mise run check         # pre-commit checks: lint + check-deps + test
mise run migrate       # python manage.py migrate
mise run makemigrations
mise run translations  # makemessages + compilemessages
```

mise loads `.env` into your shell environment, so `direnv`/`.envrc` is optional.

If you'd rather not use mise, follow the manual setup below.

## Python install & setup

### Environment variables
Copy the `.env.sample` file to `.env` and fill in the values.

### Install GIS dependencies
For MacOS, follow instructions [here](https://mits003.github.io/studio_null/2021/07/install-gdal-on-macos/).

Also, you can configure GDAL_LIBRARY_PATH and GEOS_LIBRARY_PATH env var in .env.

## Postgresql database
Works currently on postgresql 18.1, and requires postgis and pgvector extensions.

### Create the database
```shell
psql postgres
CREATE DATABASE confessio;
```
Create user and grant privileges:
```shell
CREATE USER confessio
GRANT ALL PRIVILEGES ON DATABASE confessio TO confessio;
```

### Init database from scratch
```shell
CREATE EXTENSION postgis;
CREATE EXTENSION vector;
```

The migrations can not be applied from the beginning because it crashes at some point.
If you'd like to start from scratch, you can load the prod database dump in local (see below).

To detect new migrations:
```bash
$ python manage.py makemigrations
```

To apply existing migrations:
```shell
$ python manage.py migrate
```

Create the Superuser
```bash
$ python manage.py createsuperuser
```

### Load prod database dump in local

This will download and load the latest prod database dump in local. Your psql user must be superadmin.
```bash
$ python manage.py dbrestore --uncompress
```

## Start the app

```bash
$ python manage.py runserver
```

At this point, the app runs at `http://127.0.0.1:8000/`.

## Launch the background workers

In production, there are separate workers for the main tasks and crawling tasks,
but in local you can launch a single worker for all tasks, or separate workers if you want.

All queues:
```bash
$ python manage.py process_tasks --sleep 1
```

A specific queue, and with `--dev` flag to enable auto-reload on code changes:
```bash
$ python manage.py process_tasks --queue main --sleep 1 --dev
```

## Continuous Integration

### Testing
```shell
# without django loading
python -m unittest discover -s scheduling/tests -s crawling/tests
# OR with django loading
python manage.py test
```
### Linter
```shell
flake8
```

### Pre-commit hook
Consider adding a pre-commit hook (`vim .git/hooks/pre-commit`), however if you don't, github actions will catch you.
```shell
echo "Running flake8..."
flake8 .
if [ $? -ne 0 ]; then
    echo "flake8 failed. Please fix the above issues before committing."
    exit 1
fi

echo "Checking module dependencies..."
python scripts/check_dependencies.py
if [ $? -ne 0 ]; then
    echo "Module dependency check failed. Please fix the above issues before committing."
    exit 1
fi

echo "Running unit tests..."
python -m unittest discover -s scheduling/tests -s crawling/tests
if [ $? -ne 0 ]; then
    echo "Unit tests failed. Please fix the above issues before committing."
    exit 1
fi
```

## Translations
Inside `/front` directory:
```shell
django-admin makemessages -l fr
django-admin compilemessages
```

## Commands
You'll find all implemented commands in `management/commands/` of any module. 
For example, to crawl all websites:

```shell
python manage.py crawl_websites
```

## Profiling

We use [silk](https://github.com/jazzband/django-silk) as profiling tool.
```
DJANGO_SETTINGS_MODULE=core.profiling_settings python manage.py migrate
DJANGO_SETTINGS_MODULE=core.profiling_settings python manage.py collectstatic
DJANGO_SETTINGS_MODULE=core.profiling_settings python manage.py runserver
```
Then visit http://127.0.0.1:8000/silk.

---
# Prod environment

We use ansible to deploy to production. See [ansible README](./ansible/README.md) for instructions.

### Database backup on S3
On local machine you can check S3 backups like this:
```shell
# add credentials, you will be asked for AWS access and secret key
aws configure --profile confessio
# check daily backup
aws s3 ls confessio-dbbackup-daily --profile confessio
```

### Launch Django command in prod
```shell
./prod.sh manage crawl_websites
./prod.sh manage "crawl_websites -n 'Sainte Claire Entre Loire et Rhins'"
```
and if you want to launch the command in tmux (in session "manage_tmux"):
```shell
./prod.sh manage_tmux crawl_websites
./prod.sh manage_tmux "crawl_websites -n 'Sainte Claire Entre Loire et Rhins'"
```
