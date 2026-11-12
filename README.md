# docker-hub

A simplified Docker Hub web application built with Django, developed for the
Software Configuration Management course.

## Project structure

```
dockerhub/      Django project (settings, root URLs, WSGI/ASGI)
accounts/       Custom user model (AUTH_USER_MODEL = accounts.User)
core/           Home page and health check endpoint
templates/      Shared templates (base.html)
static/         Shared static files
docs/           Class diagram
```

## Requirements

- Python 3.12+
- PostgreSQL and Redis only for the production setup (`UKS_TEST_DB=OFF`)

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

## Running tests

```bash
python manage.py test --noinput
```

## Git workflow

The project follows GitFlow: `main` holds releases, `develop` is the integration
branch, and every change is made on a `feature-<name>` or `bugfix-<name>` branch
linked to exactly one GitHub issue and merged into `develop` through a pull request.
