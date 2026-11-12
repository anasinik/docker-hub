from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.shortcuts import resolve_url
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import Role, User
from accounts.permissions import has_role

PASSWORD = "s3cret-pass"


class HasRoleTests(TestCase):
    def test_anonymous_user_has_no_role(self):
        self.assertFalse(has_role(AnonymousUser(), *Role.values))

    def test_user_has_own_role_only(self):
        admin = User.objects.create_admin(username="admin", password=PASSWORD)

        self.assertTrue(has_role(admin, Role.ADMIN))
        self.assertFalse(has_role(admin, Role.SUPER_ADMIN, Role.REGULAR_USER))


@override_settings(ROOT_URLCONF="accounts.tests.urls")
class RoleAccessTests(TestCase):
    """Integration tests: every protected view against every kind of user.

    Each URL name exists twice, once guarded by a decorator (``fbv-``) and once
    by a mixin (``cbv-``), and both must behave the same way.
    """

    # view -> roles that may access it
    ACCESS = {
        "super-admin": {Role.SUPER_ADMIN},
        "admin": {Role.SUPER_ADMIN, Role.ADMIN},
        "regular-user": {Role.REGULAR_USER},
    }

    @classmethod
    def setUpTestData(cls):
        cls.users = {
            Role.SUPER_ADMIN: User.objects.create_superuser(username="root", password=PASSWORD),
            Role.ADMIN: User.objects.create_admin(username="admin", password=PASSWORD),
            Role.REGULAR_USER: User.objects.create_user(username="alice", password=PASSWORD),
        }

    def urls(self, view):
        return [reverse(f"{kind}-{view}") for kind in ("fbv", "cbv")]

    def test_anonymous_user_is_redirected_to_login(self):
        login_url = resolve_url(settings.LOGIN_URL)

        for view in self.ACCESS:
            for url in self.urls(view):
                with self.subTest(url=url):
                    response = self.client.get(url)

                    self.assertRedirects(response, f"{login_url}?next={url}", fetch_redirect_response=False)

    def test_users_with_allowed_role_get_access(self):
        for view, allowed_roles in self.ACCESS.items():
            for role in allowed_roles:
                self.client.force_login(self.users[role])
                for url in self.urls(view):
                    with self.subTest(url=url, role=role):
                        response = self.client.get(url)

                        self.assertEqual(response.status_code, 200)
                        self.assertEqual(response.content, b"ok")

    def test_users_without_allowed_role_are_forbidden(self):
        for view, allowed_roles in self.ACCESS.items():
            for role in set(Role) - allowed_roles:
                self.client.force_login(self.users[role])
                for url in self.urls(view):
                    with self.subTest(url=url, role=role):
                        response = self.client.get(url)

                        self.assertEqual(response.status_code, 403)

    def test_access_changes_with_role(self):
        user = self.users[Role.REGULAR_USER]
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse("fbv-admin")).status_code, 403)

        user.role = Role.ADMIN
        user.save()

        self.assertEqual(self.client.get(reverse("fbv-admin")).status_code, 200)
        self.assertEqual(self.client.get(reverse("fbv-regular-user")).status_code, 403)


class AdminSiteAccessTests(TestCase):
    """Django admin access follows the role through the derived is_staff flag."""

    def test_admin_roles_can_open_admin_site(self):
        User.objects.create_superuser(username="root", password=PASSWORD)
        User.objects.create_admin(username="admin", password=PASSWORD)

        for username in ("root", "admin"):
            with self.subTest(username=username):
                self.client.login(username=username, password=PASSWORD)

                self.assertEqual(self.client.get(reverse("admin:index")).status_code, 200)

    def test_admin_form_rejects_second_super_admin(self):
        User.objects.create_superuser(username="root", password=PASSWORD)
        self.client.login(username="root", password=PASSWORD)

        response = self.client.post(
            reverse("admin:accounts_user_add"),
            {
                "username": "root2",
                "email": "root2@example.com",
                "role": Role.SUPER_ADMIN,
                "usable_password": "true",
                "password1": "An0ther-s3cret-pass",
                "password2": "An0ther-s3cret-pass",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "A super admin already exists.")
        self.assertFalse(User.objects.filter(username="root2").exists())

    def test_admin_form_creates_admin(self):
        User.objects.create_superuser(username="root", password=PASSWORD)
        self.client.login(username="root", password=PASSWORD)

        self.client.post(
            reverse("admin:accounts_user_add"),
            {
                "username": "admin",
                "email": "admin@example.com",
                "role": Role.ADMIN,
                "usable_password": "true",
                "password1": "An0ther-s3cret-pass",
                "password2": "An0ther-s3cret-pass",
            },
        )

        admin = User.objects.get(username="admin")
        self.assertEqual(admin.role, Role.ADMIN)
        self.assertTrue(admin.is_staff)
        self.assertFalse(admin.is_superuser)

    def test_regular_user_cannot_open_admin_site(self):
        User.objects.create_user(username="alice", password=PASSWORD)
        self.client.login(username="alice", password=PASSWORD)

        response = self.client.get(reverse("admin:index"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("admin:login"), response.url)
