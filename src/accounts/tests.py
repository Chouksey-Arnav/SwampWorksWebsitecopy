from django.test import TestCase
from django.urls import reverse

from .models import User

VALID = {
    'username': 'sam', 'email': 'sam@example.com',
    'password1': 'a-good-pass-123', 'password2': 'a-good-pass-123',
}


class AccountTests(TestCase):
    def test_register_logs_in(self):
        response = self.client.post(reverse('accounts:register'), VALID)
        self.assertRedirects(response, reverse('dashboard:index'))

    def test_duplicate_email_rejected_even_when_rest_is_valid(self):
        User.objects.create_user('other', 'Sam@Example.com', 'x')
        response = self.client.post(reverse('accounts:register'), VALID)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'already in use')
        self.assertEqual(User.objects.count(), 1)

    def test_logout_requires_post(self):
        User.objects.create_user('sam', 'sam@example.com', 'pw')
        self.client.login(username='sam', password='pw')
        self.assertEqual(self.client.get(reverse('accounts:logout')).status_code, 405)
        self.client.post(reverse('accounts:logout'))
        self.assertRedirects(self.client.get(reverse('dashboard:index')),
                             f"{reverse('accounts:login')}?next={reverse('dashboard:index')}")

    def test_dashboard_requires_login(self):
        self.assertEqual(self.client.get(reverse('dashboard:index')).status_code, 302)

    def test_officer_tools_only_for_staff(self):
        User.objects.create_user('member', 'm@example.com', 'pw')
        self.client.login(username='member', password='pw')
        self.assertNotContains(self.client.get(reverse('dashboard:index')), 'Officer tools')
        User.objects.create_user('officer', 'o@example.com', 'pw', is_staff=True)
        self.client.login(username='officer', password='pw')
        self.assertContains(self.client.get(reverse('dashboard:index')), 'Officer tools')
