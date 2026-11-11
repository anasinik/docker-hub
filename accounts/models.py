from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    """Custom user model for the application.

    Defined at project setup so that ``AUTH_USER_MODEL`` points to it before
    the first migration; switching to a custom user model later is painful.
    Domain fields from the class diagram (role, badge, password change flag)
    are added together with the rest of the model.
    """

    def __str__(self):
        return self.username
