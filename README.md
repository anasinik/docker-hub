# docker-hub

A simplified Docker Hub web application built with Django, developed for the
Software Configuration Management course.

## Project structure

```
dockerhub/      Django project (settings, root URLs, WSGI/ASGI)
accounts/       Custom user model (AUTH_USER_MODEL = accounts.User)
core/           Home page and health check endpoint
repositories/   Image repositories (create, list own, edit settings, delete, ...)
analytics/      Log analytics: Elasticsearch connection, log index and log shipping
templates/      Shared templates (base.html)
static/         Shared static files
docs/           Class diagram
docker/         Configuration of the docker containers
```

## Requirements

- Python 3.12+
- PostgreSQL and Redis only for the production setup (`UKS_TEST_DB=OFF`)
- Docker, only for Elasticsearch (log analytics), Nginx, and the container registry; tests do not need it

## Local development

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt

python manage.py migrate
python manage.py setup_super_admin
python manage.py runserver
```

The app is then available at http://127.0.0.1:8000/:

| Page | URL |
| --- | --- |
| Home | http://127.0.0.1:8000/ |
| Sign up | http://127.0.0.1:8000/accounts/register/ |
| Sign in | http://127.0.0.1:8000/accounts/login/ |
| Change password | http://127.0.0.1:8000/accounts/password/ |
| Administrators (super admin) | http://127.0.0.1:8000/accounts/admins/ |
| Register administrator (super admin) | http://127.0.0.1:8000/accounts/admins/new/ |
| My repositories (regular users) | http://127.0.0.1:8000/repositories/ |
| Create repository (regular users) | http://127.0.0.1:8000/repositories/new/ |
| Repository settings (owner) | http://127.0.0.1:8000/repositories/&lt;id&gt;/settings/ |
| Delete repository (owner) | http://127.0.0.1:8000/repositories/&lt;id&gt;/delete/ |
| Django admin | http://127.0.0.1:8000/admin/ |
| Health check | http://127.0.0.1:8000/health/ |

## Setup (super admin)

On the first start, `python manage.py setup_super_admin` (after `migrate`)
creates the single super admin with a generated password:

| | Default | Setting |
| --- | --- | --- |
| Username | `superadmin` | `SUPER_ADMIN_USERNAME` |
| Email | `superadmin@example.com` | `SUPER_ADMIN_EMAIL` |
| Password file | `secrets/superadmin_password.txt` (in the project directory) | `SUPER_ADMIN_PASSWORD_FILE` |

The password file contains only the password. It is created readable only by
its owner (on Linux/macOS), the `secrets/` directory is in `.gitignore`, and the
password is never printed or logged.

Sign in at `/accounts/login/` with the username and that password. Until the
password is changed, every page (the Django admin included) redirects to
`/accounts/password/`; only signing out works. `docker login` is refused as
well. The new password must be different from the generated one. After the
change, the super admin has access to everything and stays signed in. The file
is not deleted, but its password no longer works.

Running the command again does nothing once a super admin exists, so it is safe
to run on every start. If the password file is lost before the first sign-in,
set a new password with `python manage.py changepassword superadmin`.

## Users and roles

| Role | How the account is created | Notes |
| --- | --- | --- |
| Super admin | `setup_super_admin` (first start) | Only one can exist; must change the generated password |
| Admin | Registered by the super admin at `/accounts/admins/new/` | Can use the Django admin; must change the initial password |
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

### Registering administrators

Only the super admin registers administrators: "Administrators" in the header
opens `/accounts/admins/`, the list of admins (newest first, 12 per page), and
"Register administrator" opens the form at `/accounts/admins/new/`. Other users
get 403.

The form asks for a username, an email and an initial password, with the same
rules as sign-up, except that reserved usernames are allowed. The new account
always gets the Admin role. The super admin gives the initial password to the
new admin, who must change it at the first sign-in, the same way as the super
admin after setup: until then every page redirects to `/accounts/password/` and
`docker login` is refused. The list shows "Initial password not changed" for
those admins. Registrations are logged as `Admin registered` (without the password).

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
The images are deleted from the registry first, then the repository with its
tags and stars, and the user is redirected to "My repositories". If the registry
cannot be reached, nothing is deleted and the page shows an error, so old images
never stay behind for a new repository with the same name.

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
| `SUPER_ADMIN_USERNAME` | `superadmin` | Username of the super admin created by `setup_super_admin` |
| `SUPER_ADMIN_EMAIL` | `superadmin@example.com` | Email of that super admin |
| `SUPER_ADMIN_PASSWORD_FILE` | `<project>/secrets/superadmin_password.txt` | File the generated password is written to |
| `DJANGO_LOG_LEVEL` | `INFO` | Lowest level that is logged |
| `DJANGO_LOG_DIR` | `<project>/logs` | Directory of the log files |
| `DJANGO_LOG_TO_FILE` | `True` | `False` logs to the console only |
| `ELASTIC_PASSWORD` | | Password of the `elastic` user; required by `docker compose` |
| `LOG_SHIP_FILE` | `<DJANGO_LOG_DIR>/app.json.log` | File that `ship_logs` sends to Elasticsearch |
| `LOG_SHIP_BATCH_SIZE` | `500` | Log entries per bulk request |
| `ELASTICSEARCH_URL` | `http://localhost:9200` | Elasticsearch address (`http://elasticsearch:9200` inside compose) |
| `ELASTICSEARCH_USERNAME` | `elastic` | Elasticsearch user |
| `ELASTICSEARCH_LOG_INDEX` | `dockerhub-logs` | Index that stores the logs |
| `REGISTRY_PORT` | `5000` | Host port of the registry container (`docker compose`) |
| `REGISTRY_URL` | `http://127.0.0.1:5000` | Registry address (`http://registry:5000` inside compose); `localhost` is ~2 s slower per call on Windows (IPv6 first) |
| `REGISTRY_TIMEOUT` | `5` | Seconds to wait for the registry |
| `REGISTRY_CLIENT_CLASS` | `...mock.MockRegistryClient` | Registry client; `repositories.services.registry.http.HttpRegistryClient` uses the real registry |
| `REGISTRY_TOKEN_REALM` | `http://host.docker.internal:8000/registry/token/` | Token endpoint address the Docker daemon calls (`docker compose`) |
| `REGISTRY_TOKEN_SERVICE` | `dockerhub-registry` | Token audience; must match `auth.token.service` in `docker/registry/config.yml` |
| `REGISTRY_TOKEN_ISSUER` | `dockerhub-token-issuer` | Token issuer; must match `auth.token.issuer` |
| `REGISTRY_TOKEN_PRIVATE_KEY_PATH` | `docker/registry/auth/token.key` | Key that signs registry tokens |
| `REGISTRY_TOKEN_TTL` | `300` | Token lifetime in seconds |
| `REGISTRY_EVENTS_TOKEN` | | Shared secret for registry notifications (tag sync); required by `docker compose`, empty disables `/registry/events/` |
| `REGISTRY_EVENTS_URL` | `http://host.docker.internal:8000/registry/events/` | Webhook address the registry container calls (`docker compose`) |

## Logging

Logging is configured once, in `LOGGING` in [settings.py](dockerhub/settings.py).
Every message goes to the console and to two files in `DJANGO_LOG_DIR`:

| File | Format | Used by |
| --- | --- | --- |
| `app.log` | `2026-11-15 14:03:22,481 \| INFO     \| repositories.views \| Repository created: ...` | developers |
| `app.json.log` | one JSON object per line: `timestamp` (UTC), `level`, `logger`, `message`, ... | `ship_logs` -> Elasticsearch -> Analytics |

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

### Shipping logs

`ship_logs` sends the new lines of `app.json.log` to the log index
([analytics/shipping.py](analytics/shipping.py)). It creates the index if it
does not exist yet.

```bash
python manage.py ship_logs                  # once
python manage.py ship_logs --interval 30    # every 30 s until Ctrl+C
```

How it works:

- The position reached in the file (byte offset) is stored in the database
  (`LogShippingState`). Each run reads from there and saves the new offset
  only after Elasticsearch has accepted the lines.
- Lines are sent with bulk requests of `LOG_SHIP_BATCH_SIZE` entries.
- A line that is still being written (no newline yet) waits for the next run.
- Each document id is derived from the file, the offset and the line, so a
  line sent twice (after a crash or a retry) overwrites the same document
  instead of creating a duplicate.
- If Elasticsearch is down or overloaded, nothing is skipped: the same lines
  are sent on the next run. With `--interval` the command keeps running and
  retries; without it, it exits with an error.
- Lines Elasticsearch rejects for good (e.g. a field with the wrong type) and
  lines that are not JSON log entries are skipped and reported as a WARNING.
- Rotation: if `app.json.log` was renamed to `app.json.log.1`, the rest of the
  old file is sent first, then the new file from the start. A truncated file
  is read from the start. Use logrotate's default (rename), not
  `copytruncate`: if the file is truncated and grows past the old offset
  before the next run, the start of the new file is skipped.

Run only one `ship_logs` process per log file. The Elasticsearch client's own
INFO messages are not logged, otherwise every bulk request would add a line
to the file being shipped.

## Container registry

Images are stored in our own registry, [Distribution](https://distribution.github.io/distribution/) (`registry:2`), which runs as the `registry` service in [docker-compose.yml](docker-compose.yml).

The registry is configured in [docker/registry/config.yml](docker/registry/config.yml). Images are stored in the `registry_data` volume, and registry deletion through the API is enabled.

The registry is accessible to external Docker clients through the Nginx reverse proxy at `https://registry.example.com`. Nginx terminates TLS and forwards Registry API requests to the internal `registry:5000` endpoint.

Django accesses the registry directly through the internal Docker network using `http://registry:5000`.

### Local HTTPS setup

Install [mkcert](https://github.com/FiloSottile/mkcert) and initialize its local CA:

```bash
mkcert -install
```

Create the directory for Nginx certificates:

```bash
mkdir -p docker/nginx/certs
```

Generate the application certificate:

```bash
mkcert \
  -cert-file docker/nginx/certs/app-cert.pem \
  -key-file docker/nginx/certs/app-key.pem \
  localhost 127.0.0.1 ::1
```

Generate the registry certificate:

```bash
mkcert \
  -cert-file docker/nginx/certs/registry-cert.pem \
  -key-file docker/nginx/certs/registry-key.pem \
  registry.example.com
```

Add the following entry to the system hosts file:

```text
127.0.0.1 registry.example.com
```

On Windows, edit `C:\Windows\System32\drivers\etc\hosts` as Administrator. On Linux/macOS, edit `/etc/hosts`.

Start the registry and Nginx:

```bash
cp .env.example .env
# Set ELASTIC_PASSWORD in .env (required by docker-compose.yml).

# Key and certificate for registry tokens (see "Registry authentication").
# Run it before "docker compose up"; the registry does not start without
# docker/registry/auth/token.crt.
python manage.py generate_registry_keys

docker compose up -d registry nginx
docker compose ps
```

Check that the Registry API is reachable through Nginx:

**Windows (PowerShell, using curl with Schannel):**

```powershell
curl.exe --ssl-no-revoke -i https://registry.example.com/v2/
```

**Linux/macOS:**

```bash
curl -i https://registry.example.com/v2/
```

On Windows, `--ssl-no-revoke` may be needed when using locally generated `mkcert` certificates.
An unauthenticated request returns HTTP 401 with a `WWW-Authenticate: Bearer realm=...` header.

### Push and pull images

Docker clients must use the Nginx hostname rather than the internal registry service name.
Create the repository in the application first and log in with your account:

```bash
docker login registry.example.com

docker pull alpine:3.20

docker tag alpine:3.20 registry.example.com/<username>/alpine:1.0

docker push registry.example.com/<username>/alpine:1.0

docker pull registry.example.com/<username>/alpine:1.0
```

Remove the local image if needed:

```bash
docker rmi registry.example.com/<username>/alpine:1.0
```

### Registry authentication

The registry uses [token authentication](https://distribution.github.io/distribution/spec/auth/token/).
When a Docker client needs access, the registry sends it to the token endpoint
`/registry/token/` of the application (the "realm"). The application checks the
username and password, decides which actions are allowed on each requested
repository and returns a token signed with `docker/registry/auth/token.key`. The
registry verifies the token with `docker/registry/auth/token.crt` and does not
know anything about users.

`python manage.py generate_registry_keys` creates both files (`--force` replaces
them; restart the registry afterwards). The directory is in `.gitignore`.

| Who | Public repository | Private repository | Official repository (`<name>`) |
| --- | --- | --- | --- |
| Not logged in | pull | none | pull (if public) |
| Other user | pull | none | pull (if public) |
| Owner | pull, push | pull, push | - |
| Administrator | pull | none | pull, push |

- Pushing to a repository that does not exist in the application is denied; create it on the platform first.
- Users never get `delete` or `registry:catalog:*`. The application signs its own tokens for those calls (`issue_internal_token`).
- A wrong password returns 401 and is logged as `Login failed` (same as the login page). Refused actions are logged as `Registry access denied`.
- The super admin gets no token (401) until the generated password is changed on the website (see "Setup").
- The endpoint accepts `GET` (`docker login`, anonymous pulls) and `POST` with the OAuth2 password grant (containerd, used by Docker Desktop for push and pull).

The Docker daemon runs in the Docker Desktop VM, so the realm must be an address
it can reach. With the app on the host (`runserver`), start it on all interfaces
and allow the host name:

```bash
# .env: DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,host.docker.internal
python manage.py runserver 0.0.0.0:8000
```

The default realm `http://host.docker.internal:8000/registry/token/` then works.
Set `REGISTRY_TOKEN_REALM` in `.env` and restart the registry when the app runs elsewhere.

### Tag sync

Tags are shown from the `Tag` table, so repository pages do not call the
registry. The registry stays the source of truth; the table mirrors it:

- After every push or delete the registry sends a notification to
  `/registry/events/` (configured in `docker-compose.yml`, authenticated with
  `REGISTRY_EVENTS_TOKEN`). The app then reads the repository's tags through the
  registry API: tag list, digest of each tag (`HEAD`), and the manifest only for
  new or changed digests. A multi-arch push sends one event per platform, but
  only the tagged index starts a sync.
- `python manage.py sync_registry` syncs all repositories (`--repository alice/web`
  for one), e.g. after the app was down while images were pushed.

For each tag the app stores the digest, the manifest type and the compressed
size (config and layers; summed over platforms for a multi-arch image). The
registry does not store push times, so "Last pushed" is the time of the push
event, or of the first sync that saw the digest.

The app talks to the registry with `HttpRegistryClient` (set
`REGISTRY_CLIENT_CLASS=repositories.services.registry.http.HttpRegistryClient`);
it signs its own tokens, so it needs the key from `generate_registry_keys`. The
default `MockRegistryClient` has no images, so `runserver`, tests and CI work
without the container. With the mock, `/registry/events/` (503) and
`sync_registry` refuse to sync and log a warning, because a sync against a
registry without images would delete every tag in the database.

### Deleting images

Deleting a repository deletes its manifests through the registry API. The layer
files stay on disk until the registry's garbage collector removes them:

```bash
docker compose exec registry bin/registry garbage-collect /etc/docker/registry/config.yml
```

Run it when nobody is pushing (pushes during garbage collection can lose layers).

To delete all images, stop and remove the registry container, then remove the `registry_data` volume. Avoid `docker compose down -v` if you want to preserve Elasticsearch logs.

## Running tests

```bash
python manage.py test --noinput
```

## Git workflow

The project follows GitFlow: `main` holds releases, `develop` is the integration
branch, and every change is made on a `feature-<name>` or `bugfix-<name>` branch
linked to exactly one GitHub issue and merged into `develop` through a pull request.
