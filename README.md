# docker-hub

A simplified Docker Hub web application built with Django, developed for the
Software Configuration Management course.

## Project structure

```
dockerhub/      Django project (settings, root URLs, WSGI/ASGI)
accounts/       Custom user model (AUTH_USER_MODEL = accounts.User)
core/           Home page and health check endpoint
repositories/   Image repositories (create, list own, edit settings, ...)
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
| Sign in | http://127.0.0.1:8000/accounts/login/ |
| My repositories (regular users) | http://127.0.0.1:8000/repositories/ |
| Create repository (regular users) | http://127.0.0.1:8000/repositories/new/ |
| Repository settings (owner) | http://127.0.0.1:8000/repositories/&lt;id&gt;/settings/ |
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
