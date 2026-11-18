# docker-hub

A simplified Docker Hub web application built with Django, developed for the
Software Configuration Management course.

## Project structure

```
dockerhub/      Django project (settings, root URLs, WSGI/ASGI)
accounts/       Custom user model (AUTH_USER_MODEL = accounts.User)
core/           Home page and health check endpoint
repositories/   Image repositories (create, list own, edit settings, delete, ...)
analytics/      Log analytics: Elasticsearch connection and log index
templates/      Shared templates (base.html)
static/         Shared static files
docs/           Class diagram
```

## Requirements

- Python 3.12+
- PostgreSQL and Redis only for the production setup (`UKS_TEST_DB=OFF`)
- Docker, only for Elasticsearch (log analytics); tests do not need it

## Local development

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt

python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

The app is then available at http://127.0.0.1:8000/:

| Page | URL |
| --- | --- |
| Home | http://127.0.0.1:8000/ |
| Sign up | http://127.0.0.1:8000/accounts/register/ |
| Sign in | http://127.0.0.1:8000/accounts/login/ |
| My repositories (regular users) | http://127.0.0.1:8000/repositories/ |
| Create repository (regular users) | http://127.0.0.1:8000/repositories/new/ |
| Repository settings (owner) | http://127.0.0.1:8000/repositories/&lt;id&gt;/settings/ |
| Delete repository (owner) | http://127.0.0.1:8000/repositories/&lt;id&gt;/delete/ |
| Django admin | http://127.0.0.1:8000/admin/ |
| Health check | http://127.0.0.1:8000/health/ |

`createsuperuser` creates the single super admin and asks for an email, which is required.

## Users and roles

| Role | How the account is created | Notes |
| --- | --- | --- |
| Super admin | `createsuperuser` | Only one can exist |
| Admin | Added by the super admin | Can use the Django admin |
| Regular user | Signs up at `/accounts/register/` | Default role |

Usernames are 4-30 lowercase letters and digits, because they are also the
repository namespace (`username/repository`). Names such as `library`, `admin`
and `official` are reserved and cannot be taken at sign-up. Emails are required
and unique, ignoring case.

All roles sign in at `/accounts/login/` with their username or email (case does
not matter). After signing in, users return to the page they came from, or to
the home page. Pages that need a login send visitors there. "Sign out" in the
header ends the session; logout only accepts POST, so other sites cannot sign
users out with a link. Successful logins, failed logins and logouts are logged.

## Repositories

Regular users create repositories at `/repositories/new/`. Admins cannot (they
get 403); they manage official repositories instead. A repository belongs to the
user who created it, and its images are addressed as `username/repository`
(for example `alice/my-app`).

- Names are 2-100 characters: lowercase letters and digits, optionally separated
  by a single `.`, `_` or `-` (Docker's rules for image names). Input is lowercased.
- A user cannot have two repositories with the same name; different users can.
- The description is optional and up to 100 characters.
- Visibility is `Public` (default) or `Private`.

Regular users see all their own repositories, public and private, at
`/repositories/` ("My repositories" in the header). The list is sorted by last
update, 12 per page, and shows each repository's star count. After creating a
repository, the user is redirected to this list.

The owner can change a repository's description and visibility at
`/repositories/<id>/settings/` (the "Settings" button on the repository page).
The name cannot be changed, because it is part of the image path. Other users
get 404 and admins get 403.

The owner deletes a repository from the "Danger zone" on its settings page, at
`/repositories/<id>/delete/`. To confirm, the owner types the repository name.
The repository and its stars are deleted, and the user is redirected to
"My repositories". Images in the registry will be deleted too once the
registry is set up.

## Configuration

Settings are read from environment variables. See [.env.example](.env.example)
for the full list.

| Variable | Default | Description |
| --- | --- | --- |
| `UKS_TEST_DB` | `ON` | `ON` uses SQLite and a local memory cache; `OFF` uses PostgreSQL and Redis |
| `DJANGO_SECRET_KEY` | insecure dev key | Must be set in production |
| `DJANGO_DEBUG` | `True` | Set to `False` in production |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated host names |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, `POSTGRES_PORT` | | PostgreSQL connection |
| `REDIS_URL` | `redis://redis:6379/0` | Redis cache location |
| `DJANGO_LOG_LEVEL` | `INFO` | Lowest level that is logged |
| `DJANGO_LOG_DIR` | `<project>/logs` | Directory of the log files |
| `DJANGO_LOG_TO_FILE` | `True` | `False` logs to the console only |
| `ELASTIC_PASSWORD` | | Password of the `elastic` user; required by `docker compose` |
| `ELASTICSEARCH_URL` | `http://localhost:9200` | Elasticsearch address (`http://elasticsearch:9200` inside compose) |
| `ELASTICSEARCH_USERNAME` | `elastic` | Elasticsearch user |
| `ELASTICSEARCH_LOG_INDEX` | `dockerhub-logs` | Index that stores the logs |

## Logging

Logging is configured once, in `LOGGING` in [settings.py](dockerhub/settings.py).
Every message goes to the console and to two files in `DJANGO_LOG_DIR`:

| File | Format | Used by |
| --- | --- | --- |
| `app.log` | `2026-11-15 14:03:22,481 \| INFO     \| repositories.views \| Repository created: ...` | developers |
| `app.json.log` | one JSON object per line: `timestamp` (UTC), `level`, `logger`, `message`, ... | Filebeat -> Elasticsearch -> Analytics |

The files are not rotated by the app: several Gunicorn workers write to them,
so rotation is left to an external tool (logrotate); the app reopens a file
once it has been rotated. While tests run, nothing is logged to the console or
to files.

Every HTTP request is logged by `core.middleware.RequestLoggingMiddleware`
(logger `dockerhub.requests`): method, path, status, duration, user and IP, as
INFO (2xx/3xx), WARNING (4xx) or ERROR (5xx). Static files and `/health/` are
skipped.

### Logging in your code

```python
import logging

logger = logging.getLogger(__name__)  # e.g. "repositories.views"

logger.info("Repository created: path=%s id=%s", repository.registry_path, repository.pk)
```

- Use `%s` arguments, not f-strings: the message is formatted only if it is logged.
- Log user input with `%r`, so newlines cannot forge extra log lines.
- Never log passwords, tokens or other secrets.
- Fields passed as `extra={"repo_id": repository.pk}` become separate
  fields in `app.json.log`, so they can be searched in Elasticsearch. Rules:
  - use specific names (`repo_id`, `duration_ms`, `client_ip`), and prefix them
    with your app when a name could mean different things (`repo_visibility`,
    not `visibility`);
  - never use ECS names (`user`, `host`, `log`, `event`, `process`, `client`,
    `http`) or LogRecord attributes (`name`, `module`, `message`, ...);
  - values are plain strings, numbers or booleans, of the same type in every call.
- In an `except` block, use `logger.exception("...")` to include the traceback.

| Level | When |
| --- | --- |
| `DEBUG` | Details only needed while debugging (hidden by default) |
| `INFO` | Normal events: user registered, logged in, repository created or deleted |
| `WARNING` | Something unexpected that the app handled: failed login, forbidden action, registry unavailable |
| `ERROR` | An operation failed: database unavailable, unhandled exception |
| `CRITICAL` | The whole app cannot work (not used yet) |

Tests can check log messages with `self.assertLogs("repositories.views", level="INFO")`.

## Elasticsearch

Logs from `app.json.log` are stored in Elasticsearch so the Analytics section
can search them. Elasticsearch runs in Docker ([docker-compose.yml](docker-compose.yml)):
a single node with authentication enabled and no TLS (local development only).

```bash
cp .env.example .env            # then set ELASTIC_PASSWORD
docker compose up -d elasticsearch
docker compose ps               # wait until the container is "healthy" (~30 s)
curl -u elastic:<password> http://localhost:9200
```

The password is set only when the `es_data` volume is created. To start over
with a new password, run `docker compose down -v` (this deletes all stored logs).

The app connects with the `ELASTICSEARCH_*` settings
([analytics/elasticsearch.py](analytics/elasticsearch.py)). The connection is lazy,
so `runserver`, tests and CI work without Elasticsearch. Create the log index
once (running it again only adds new fields to the mapping):

```bash
# Linux/macOS/Git Bash: export ELASTIC_PASSWORD=<password>   PowerShell: $env:ELASTIC_PASSWORD="<password>"
python manage.py init_elasticsearch             # --recreate deletes the index first
```

The index mapping is `LogEntry` in [analytics/documents.py](analytics/documents.py):
one field per key that `JsonFormatter` writes, plus the request fields
(`http_status`, `duration_ms`, `client_ip`, ...). A new `extra={...}` field is
mapped automatically as a `keyword`; add it to `LogEntry` if it needs another
type (number, date, IP).

## Running tests

```bash
python manage.py test --noinput
```

## Git workflow

The project follows GitFlow: `main` holds releases, `develop` is the integration
branch, and every change is made on a `feature-<name>` or `bugfix-<name>` branch
linked to exactly one GitHub issue and merged into `develop` through a pull request.
