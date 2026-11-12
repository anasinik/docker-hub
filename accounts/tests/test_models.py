from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from accounts.models import Role, User


class UserModelTests(TestCase):
    def test_custom_user_model_is_active(self):
        self.assertIs(get_user_model(), User)

    def test_create_user(self):
        user = User.objects.create_user(username="alice", email="alice@example.com", password="s3cret-pass")

        self.assertEqual(str(user), "alice")
        self.assertTrue(user.check_password("s3cret-pass"))


class UsernameRulesTests(TestCase):
    def build_user(self, username):
        user = User(username=username, email=f"{username}@example.com")
        user.set_password("s3cret-pass")
        return user

    def test_valid_usernames(self):
        for username in ("alic", "alice", "alice2025", "a" * 30):
            with self.subTest(username=username):
                self.build_user(username).full_clean()

    def test_invalid_usernames(self):
        for username in ("abc", "a" * 31, "Alice", "alice.smith", "alice_smith", "alice-smith", "alice smith", "alice@x"):
            with self.subTest(username=username):
                with self.assertRaises(ValidationError) as context:
                    self.build_user(username).full_clean()

                self.assertIn("username", context.exception.message_dict)

    def test_reserved_username_is_allowed_outside_sign_up(self):
        # Reserved names are only blocked for self-registration.
        self.build_user("admin").full_clean()


class EmailRulesTests(TestCase):
    def test_email_is_required(self):
        user = User(username="alice")
        user.set_password("s3cret-pass")

        with self.assertRaises(ValidationError) as context:
            user.full_clean()

        self.assertIn("email", context.exception.message_dict)

    def test_email_must_be_unique_ignoring_case(self):
        User.objects.create_user(username="alice", email="alice@example.com", password="s3cret-pass")

        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create_user(username="alice2", email="ALICE@example.com", password="s3cret-pass")

    def test_duplicate_email_fails_validation(self):
        User.objects.create_user(username="alice", email="alice@example.com", password="s3cret-pass")
        user = User(username="alice2", email="Alice@Example.com")
        user.set_password("s3cret-pass")

        with self.assertRaisesMessage(ValidationError, "A user with this email already exists."):
            user.full_clean()


class UserRoleTests(TestCase):
    def test_new_user_is_regular_user_by_default(self):
        user = User.objects.create_user(username="alice", password="s3cret-pass")

        self.assertEqual(user.role, Role.REGULAR_USER)
        self.assertTrue(user.is_regular_user)
        self.assertFalse(user.is_admin)
        self.assertFalse(user.is_super_admin)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_create_admin(self):
        admin = User.objects.create_admin(username="admin", password="s3cret-pass")

        self.assertEqual(admin.role, Role.ADMIN)
        self.assertTrue(admin.is_admin)
        self.assertFalse(admin.is_super_admin)
        self.assertFalse(admin.is_regular_user)
        self.assertTrue(admin.is_staff)
        self.assertFalse(admin.is_superuser)

    def test_create_superuser_gets_super_admin_role(self):
        super_admin = User.objects.create_superuser(username="root", password="s3cret-pass")

        self.assertEqual(super_admin.role, Role.SUPER_ADMIN)
        self.assertTrue(super_admin.is_super_admin)
        self.assertTrue(super_admin.is_admin)
        self.assertFalse(super_admin.is_regular_user)
        self.assertTrue(super_admin.is_staff)
        self.assertTrue(super_admin.is_superuser)

    def test_flags_follow_role_changes(self):
        user = User.objects.create_user(username="alice", password="s3cret-pass")

        user.role = Role.ADMIN
        user.save()
        user.refresh_from_db()
        self.assertTrue(user.is_staff)
        self.assertFalse(user.is_superuser)

        user.role = Role.REGULAR_USER
        user.save()
        user.refresh_from_db()
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_flags_cannot_be_set_independently_of_role(self):
        user = User.objects.create_user(username="alice", password="s3cret-pass", is_staff=True, is_superuser=True)

        user.refresh_from_db()
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_flags_are_saved_with_update_fields(self):
        user = User.objects.create_user(username="alice", password="s3cret-pass")

        user.role = Role.ADMIN
        user.save(update_fields=["role"])
        user.refresh_from_db()

        self.assertEqual(user.role, Role.ADMIN)
        self.assertTrue(user.is_staff)

    def test_manager_role_querysets(self):
        root = User.objects.create_superuser(username="root", password="s3cret-pass")
        admin = User.objects.create_admin(username="admin", password="s3cret-pass")
        alice = User.objects.create_user(username="alice", password="s3cret-pass")

        self.assertCountEqual(User.objects.admins(), [root, admin])
        self.assertCountEqual(User.objects.regular_users(), [alice])


class SingleSuperAdminTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.super_admin = User.objects.create_superuser(username="root", email="root@example.com", password="s3cret-pass")

    def test_second_super_admin_is_rejected_by_database(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create_superuser(username="root2", password="s3cret-pass")

    def test_second_super_admin_fails_validation(self):
        user = User(username="root2", role=Role.SUPER_ADMIN)
        user.set_password("s3cret-pass")

        with self.assertRaisesMessage(ValidationError, "A super admin already exists."):
            user.full_clean()

    def test_existing_super_admin_passes_validation(self):
        self.super_admin.full_clean()

    def test_multiple_admins_are_allowed(self):
        User.objects.create_admin(username="admin1", password="s3cret-pass")
        User.objects.create_admin(username="admin2", password="s3cret-pass")

        self.assertEqual(User.objects.filter(role=Role.ADMIN).count(), 2)
