from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    @property
    def display_name(self):
        """What other people see. First name if given, else username. Never the email."""
        return self.first_name.strip() or self.username
