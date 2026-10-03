"""Demo data for local development: subjects, tutors and open times.

    python manage.py seed_tutoring            # add demo tutors (idempotent)
    python manage.py seed_tutoring --reset    # remove demo tutors first

Tutor accounts are named demo_* and have no usable password. Refuses to run with DEBUG off
unless --force, so demo tutors can't end up on the live site by accident.
"""
from datetime import datetime, time, timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from accounts.models import User
from landing_page.models import Meeting, Project
from tutoring.models import AvailabilitySlot, Subject, TutorProfile

SUBJECTS = {
    'math': ['Algebra', 'Geometry', 'Calculus', 'Statistics', 'SAT Math'],
    'science': ['Chemistry', 'Biology', 'Physics'],
    'english': ['English', 'Essay writing'],
    'cs': ['Python', 'Computer science'],
    'languages': ['Spanish'],
    'social': ['US History', 'Government'],
}

# username, display name, grade, headline, bio, subjects, weekdays (0=Mon), start hour, slots per day
TUTORS = [
    ('demo_maya', 'Maya R.', 'Senior', 'AP Calculus BC and Statistics',
     'I took Calc BC as a junior and got a 5. I like finding the one idea that makes a topic click, then practicing until it sticks.',
     ['Calculus', 'Statistics', 'Algebra'], [0, 2, 3], 15, 4),
    ('demo_jordan', 'Jordan K.', 'Junior', 'Chemistry and Biology, from lab reports to the AP exam',
     'Lab partner you wish you had. I can walk through stoichiometry, check your lab report, or quiz you before a test.',
     ['Chemistry', 'Biology'], [1, 3], 15, 3),
    ('demo_priya', 'Priya S.', 'Senior', 'Essay structure, AP Lang, and college application writing',
     "I'll help you get from a blank page to a clear argument. Bring a draft or just a topic.",
     ['English', 'Essay writing'], [0, 1, 4], 15, 3),
    ('demo_devon', 'Devon T.', 'Sophomore', 'Python for beginners and first-year computer science',
     'Stuck on loops, functions or a bug that makes no sense? Bring your code and we will read it together.',
     ['Python', 'Computer science'], [2, 4], 16, 4),
    ('demo_sam', 'Sam L.', 'Junior', 'Geometry, Algebra 2 and SAT math',
     'Patient, and big on showing every step. Great for catching up or getting ahead.',
     ['Geometry', 'Algebra', 'SAT Math'], [0, 1, 2, 3], 15, 2),
    ('demo_alex', 'Alex W.', 'Senior', 'Physics C: mechanics without the tears',
     'Free-body diagrams, energy, rotation. I draw a lot.',
     ['Physics', 'Calculus'], [3], 16, 2),
    ('demo_noor', 'Noor A.', 'Junior', 'Spanish conversation and grammar for Spanish 2 to 4',
     'Native speaker. We can practice talking, fix verb tenses, or prep for an oral exam.',
     ['Spanish'], [1, 4], 15, 3),
    ('demo_eli', 'Eli B.', 'Senior', 'US History and AP Government',
     'I build timelines and make the cause and effect obvious. Currently booked up, check back soon.',
     ['US History', 'Government'], [], 15, 0),
]


class Command(BaseCommand):
    help = 'Create demo tutoring data for development.'

    def add_arguments(self, parser):
        parser.add_argument('--reset', action='store_true', help='Delete existing demo tutors first.')
        parser.add_argument('--force', action='store_true', help='Allow running with DEBUG off.')

    def handle(self, *args, reset=False, force=False, **options):
        if not settings.DEBUG and not force:
            raise CommandError('Refusing to seed demo tutors with DEBUG off. Pass --force if you really mean it.')
        if reset:
            User.objects.filter(username__startswith='demo_').delete()

        by_name = {}
        for category, names in SUBJECTS.items():
            for name in names:
                by_name[name], _ = Subject.objects.get_or_create(name=name, defaults={'category': category})

        tz = timezone.get_current_timezone()
        today = timezone.localdate()
        made_slots = 0
        for username, name, grade, headline, bio, subjects, weekdays, hour, per_day in TUTORS:
            user, _ = User.objects.get_or_create(username=username, defaults={'first_name': name.split()[0]})
            user.set_unusable_password()
            user.save()
            profile, _ = TutorProfile.objects.update_or_create(
                user=user, defaults=dict(display_name=name, grade_label=grade, headline=headline, bio=bio,
                                         location='Media Center, table 4', is_listed=True))
            profile.subjects.set([by_name[s] for s in subjects])
            for offset in range(0, 21):
                day = today + timedelta(days=offset)
                if day.weekday() not in weekdays:
                    continue
                for i in range(per_day):
                    start = datetime.combine(day, time(hour, 0), tzinfo=tz) + timedelta(minutes=30 * i)
                    end = start + timedelta(minutes=30)
                    if start < timezone.now() + timedelta(hours=settings.TUTORING_MIN_NOTICE_HOURS):
                        continue
                    _, created = AvailabilitySlot.objects.get_or_create(tutor=profile, start=start, defaults={'end': end})
                    made_slots += created

        if not Meeting.objects.exists():
            start = datetime.combine(today + timedelta(days=(2 - today.weekday()) % 7 or 7), time(15, 30), tzinfo=tz)
            Meeting.objects.create(title='New members meeting', date=start, location='Room 214', notes='Pizza provided.')
        if not Project.objects.exists():
            Project.objects.create(title='This website', summary='Student tutoring, booking and chat, built by members.',
                                   status='active', lead='Tech team', next_step='Tutor sign-up flow', next_step_date=today + timedelta(days=14))
            Project.objects.create(title='Library check-in kiosk', summary='A simple sign-in screen for the media center.', status='planning', lead='Open')

        self.stdout.write(self.style.SUCCESS(f'Seeded {len(TUTORS)} demo tutors and {made_slots} new open times.'))
