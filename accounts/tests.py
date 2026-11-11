from django.contrib.auth import get_user_model
from django.test import TestCase

from .models import User


class UserModelTests(TestCase):
    def test_custom_user_model_is_active(self):
        self.assertIs(get_user_model(), User)

    def test_create_user(self):
        user = User.objects.create_user(username="alice", email="alice@example.com", password="s3cret-pass")

        self.assertEqual(str(user), "alice")
        self.assertTrue(user.check_password("s3cret-pass"))
        self.assertFalse(user.is_staff)
