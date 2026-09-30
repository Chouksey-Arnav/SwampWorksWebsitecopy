from datetime import timedelta

from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import JoinRequest, Meeting, Project, ProjectIdea


class PublicPagesTests(TestCase):
    def test_pages_load(self):
        for name in ['index', 'about', 'projects', 'calendar', 'contact', 'ideas']:
            with self.subTest(page=name):
                self.assertEqual(self.client.get(reverse(f'landing_page:{name}')).status_code, 200)

    def test_index_shows_next_meeting_and_projects(self):
        Meeting.objects.create(title='Kickoff', date=timezone.now() + timedelta(days=3))
        Meeting.objects.create(title='Old one', date=timezone.now() - timedelta(days=3))
        Project.objects.create(title='Club site', summary='This site')
        response = self.client.get(reverse('landing_page:index'))
        self.assertContains(response, 'Kickoff')
        self.assertNotContains(response, 'Old one')
        self.assertContains(response, 'Club site')

    def test_calendar_splits_upcoming_and_past(self):
        Meeting.objects.create(title='Future', date=timezone.now() + timedelta(days=1))
        Meeting.objects.create(title='Past', date=timezone.now() - timedelta(days=1))
        response = self.client.get(reverse('landing_page:calendar'))
        self.assertEqual([m.title for m in response.context['upcoming']], ['Future'])
        self.assertEqual([m.title for m in response.context['past']], ['Past'])


class FormTests(TestCase):
    def test_join_saves_and_emails_officers(self):
        response = self.client.post(reverse('landing_page:contact'), {
            'name': 'Sam', 'email': 'sam@example.com', 'grade': '10', 'message': '',
        }, follow=True)
        self.assertEqual(JoinRequest.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertContains(response, 'Thanks!')

    def test_join_requires_valid_email(self):
        self.client.post(reverse('landing_page:contact'), {'name': 'Sam', 'email': 'nope'})
        self.assertEqual(JoinRequest.objects.count(), 0)

    def test_idea_saves(self):
        self.client.post(reverse('landing_page:ideas'), {
            'source': 'community', 'title': 'Library kiosk', 'description': 'A sign-in kiosk',
        })
        self.assertEqual(ProjectIdea.objects.get().source, 'community')
