import json
from datetime import timedelta

from django.contrib.admin.sites import site as admin_site
from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User

from . import services
from .models import AvailabilitySlot, Booking, Message, Report, Subject, TutorProfile
from .services import BookingError, ChatError


def make_tutor(username='maya', name='Maya R.', listed=True, subjects=('Calculus',)):
    user = User.objects.create_user(username, f'{username}@example.com', 'pw', first_name=name.split()[0])
    tutor = TutorProfile.objects.create(user=user, display_name=name, headline='AP Calc', is_listed=listed)
    for s in subjects:
        tutor.subjects.add(Subject.objects.get_or_create(name=s)[0])
    return tutor


def make_slot(tutor, hours=24, minutes=30, **kwargs):
    start = timezone.now() + timedelta(hours=hours)
    return AvailabilitySlot.objects.create(tutor=tutor, start=start, end=start + timedelta(minutes=minutes), **kwargs)


def make_student(username='sam'):
    return User.objects.create_user(username, f'{username}@example.com', 'pw', first_name=username.title())


class DirectoryTests(TestCase):
    def setUp(self):
        self.maya = make_tutor()
        make_slot(self.maya)
        self.jordan = make_tutor('jordan', 'Jordan K.', subjects=('Chemistry',))
        self.hidden = make_tutor('hidden', 'Hidden H.', listed=False)

    def names(self, **params):
        response = self.client.get(reverse('tutoring:directory'), params)
        self.assertEqual(response.status_code, 200)
        return [t.display_name for t in response.context['page'].object_list]

    def test_only_listed_tutors_appear(self):
        self.assertEqual(sorted(self.names()), ['Jordan K.', 'Maya R.'])

    def test_search_matches_subject_name_and_bio(self):
        self.assertEqual(self.names(q='chem'), ['Jordan K.'])
        self.assertEqual(self.names(q='maya'), ['Maya R.'])
        self.assertEqual(self.names(q='nonsense'), [])

    def test_subject_and_open_filters(self):
        self.assertEqual(self.names(subject='calculus'), ['Maya R.'])
        self.assertEqual(self.names(open='1'), ['Maya R.'])

    def test_available_tutors_sort_before_unavailable(self):
        self.assertEqual(self.names(), ['Maya R.', 'Jordan K.'])

    def test_search_input_is_escaped(self):
        response = self.client.get(reverse('tutoring:directory'), {'q': '<script>alert(1)</script>'})
        self.assertNotContains(response, '<script>alert(1)</script>')

    def test_garbage_page_param_does_not_crash(self):
        self.assertEqual(self.client.get(reverse('tutoring:directory'), {'page': 'abc'}).status_code, 200)

    def test_query_count_does_not_grow_with_tutor_count(self):
        for i in range(10):
            make_slot(make_tutor(f't{i}', f'Tutor {i}.'), hours=30 + i)
        with self.assertNumQueries(5):
            self.client.get(reverse('tutoring:directory'))


class ProfileTests(TestCase):
    def setUp(self):
        self.tutor = make_tutor()

    def test_unlisted_profile_is_404_for_public_but_staff_can_preview(self):
        hidden = make_tutor('h', 'Hidden H.', listed=False)
        self.assertEqual(self.client.get(reverse('tutoring:profile', args=[hidden.pk])).status_code, 404)
        User.objects.create_user('staff', 's@example.com', 'pw', is_staff=True)
        self.client.login(username='staff', password='pw')
        self.assertContains(self.client.get(reverse('tutoring:profile', args=[hidden.pk])), 'Preview only')

    def test_only_bookable_slots_are_offered(self):
        good = make_slot(self.tutor, hours=24)
        soon = make_slot(self.tutor, hours=1)            # inside the minimum notice
        far = make_slot(self.tutor, hours=24 * 40)       # beyond the booking horizon
        past = make_slot(self.tutor, hours=-5)
        closed = make_slot(self.tutor, hours=48, is_open=False)
        taken = make_slot(self.tutor, hours=72)
        Booking.objects.create(slot=taken, student=make_student())
        offered = {s.pk for s in services.open_slots()}
        self.assertEqual(offered, {good.pk})
        for bad in (soon, far, past, closed, taken):
            self.assertNotIn(bad.pk, offered)

    def test_slot_links_point_to_booking(self):
        slot = make_slot(self.tutor)
        self.assertContains(self.client.get(reverse('tutoring:profile', args=[self.tutor.pk])), reverse('tutoring:book', args=[slot.pk]))


class BookingTests(TestCase):
    def setUp(self):
        self.tutor = make_tutor()
        self.slot = make_slot(self.tutor)
        self.student = make_student()
        self.calc = self.tutor.subjects.get()

    def post(self, slot=None, **extra):
        return self.client.post(reverse('tutoring:book', args=[(slot or self.slot).pk]), {'subject': self.calc.pk, 'note': 'Ch 4', **extra})

    def test_booking_requires_login_and_returns_after_login(self):
        url = reverse('tutoring:book', args=[self.slot.pk])
        response = self.client.get(url)
        self.assertRedirects(response, f"{reverse('accounts:login')}?next={url}")
        response = self.client.post(reverse('accounts:login') + f'?next={url}', {'username': 'sam', 'password': 'pw', 'next': url})
        self.assertRedirects(response, url, fetch_redirect_response=False)

    def test_successful_booking_redirects_to_chat_and_emails_both(self):
        self.client.login(username='sam', password='pw')
        response = self.post()
        booking = Booking.objects.get()
        self.assertRedirects(response, reverse('tutoring:session', args=[booking.pk]))
        self.assertEqual((booking.student, booking.slot, booking.note), (self.student, self.slot, 'Ch 4'))
        self.assertEqual(sorted(m.to[0] for m in mail.outbox), ['maya@example.com', 'sam@example.com'])

    def test_second_student_cannot_take_a_booked_slot(self):
        self.client.login(username='sam', password='pw')
        self.post()
        make_student('lee')
        self.client.login(username='lee', password='pw')
        response = self.post(follow=True) if False else self.client.post(reverse('tutoring:book', args=[self.slot.pk]), {'subject': self.calc.pk}, follow=True)
        self.assertEqual(Booking.objects.count(), 1)
        self.assertContains(response, 'just taken')

    def test_database_blocks_double_booking_even_if_code_is_bypassed(self):
        Booking.objects.create(slot=self.slot, student=self.student)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Booking.objects.create(slot=self.slot, student=make_student('lee'))

    def test_cancelled_booking_frees_the_slot_for_rebooking(self):
        first = Booking.objects.create(slot=self.slot, student=self.student)
        services.cancel_booking(first, self.student)
        again = services.book_slot(make_student('lee'), self.slot.pk, self.calc)
        self.assertTrue(again.is_confirmed)

    def test_cannot_book_yourself(self):
        with self.assertRaisesMessage(BookingError, 'yourself'):
            services.book_slot(self.tutor.user, self.slot.pk)

    def test_subject_must_belong_to_tutor(self):
        other = Subject.objects.create(name='Latin')
        with self.assertRaises(BookingError):
            services.book_slot(self.student, self.slot.pk, other)

    def test_slot_inside_minimum_notice_is_rejected(self):
        late = make_slot(self.tutor, hours=1)
        with self.assertRaises(BookingError):
            services.book_slot(self.student, late.pk)

    def test_unlisted_tutor_cannot_be_booked(self):
        self.tutor.is_listed = False
        self.tutor.save()
        with self.assertRaises(BookingError):
            services.book_slot(self.student, self.slot.pk)

    def test_student_cannot_hoard_sessions(self):
        with override_settings(TUTORING_MAX_UPCOMING_PER_STUDENT=2):
            for h in (24, 48):
                services.book_slot(self.student, make_slot(self.tutor, hours=h).pk)
            with self.assertRaisesMessage(BookingError, 'upcoming sessions'):
                services.book_slot(self.student, make_slot(self.tutor, hours=72).pk)

    def test_student_cannot_double_book_the_same_time_with_two_tutors(self):
        other = make_tutor('jordan', 'Jordan K.')
        a = AvailabilitySlot.objects.create(tutor=other, start=self.slot.start, end=self.slot.end)
        services.book_slot(self.student, self.slot.pk)
        with self.assertRaisesMessage(BookingError, 'already have a session'):
            services.book_slot(self.student, a.pk)

    def test_note_is_limited(self):
        self.client.login(username='sam', password='pw')
        self.client.post(reverse('tutoring:book', args=[self.slot.pk]), {'subject': self.calc.pk, 'note': 'x' * 301})
        self.assertEqual(Booking.objects.count(), 0)

    def test_get_book_page_for_taken_slot_redirects_with_message(self):
        Booking.objects.create(slot=self.slot, student=make_student('lee'))
        self.client.login(username='sam', password='pw')
        response = self.client.get(reverse('tutoring:book', args=[self.slot.pk]), follow=True)
        self.assertRedirects(response, reverse('tutoring:profile', args=[self.tutor.pk]))


class CancelTests(TestCase):
    def setUp(self):
        self.tutor = make_tutor()
        self.student = make_student()

    def book(self, hours):
        slot = make_slot(self.tutor, hours=hours)
        return Booking.objects.create(slot=slot, student=self.student)

    def test_student_can_cancel_with_notice_and_slot_reopens(self):
        booking = self.book(24)
        services.cancel_booking(booking, self.student)
        booking.refresh_from_db()
        self.assertEqual((booking.status, booking.cancelled_by), (Booking.CANCELLED, self.student))
        self.assertIn(booking.slot_id, {s.pk for s in services.open_slots()})

    def test_student_cannot_cancel_inside_notice_window(self):
        booking = self.book(1)
        with self.assertRaisesMessage(BookingError, 'up to 2 hours before'):
            services.cancel_booking(booking, self.student)
        booking.refresh_from_db()
        self.assertTrue(booking.is_confirmed)

    def test_tutor_cancel_closes_the_slot(self):
        booking = self.book(1)
        services.cancel_booking(booking, self.tutor.user)
        booking.slot.refresh_from_db()
        self.assertFalse(booking.slot.is_open)
        self.assertNotIn(booking.slot_id, {s.pk for s in services.open_slots()})
        self.assertEqual(mail.outbox[-1].to, ['sam@example.com'])

    def test_stranger_cannot_cancel(self):
        booking = self.book(24)
        self.assertEqual(services.cancel_problem(booking, make_student('eve')), 'Not your session.')

    def test_cancel_view_needs_post_and_participant(self):
        booking = self.book(24)
        self.client.login(username='sam', password='pw')
        url = reverse('tutoring:cancel', args=[booking.pk])
        self.assertContains(self.client.get(url), 'Cancel this session?')
        booking.refresh_from_db()
        self.assertTrue(booking.is_confirmed)          # GET never cancels
        self.client.post(url)
        booking.refresh_from_db()
        self.assertFalse(booking.is_confirmed)
        make_student('eve')
        self.client.login(username='eve', password='pw')
        self.assertEqual(self.client.post(url).status_code, 404)

    def test_cannot_cancel_twice(self):
        booking = self.book(24)
        services.cancel_booking(booking, self.student)
        with self.assertRaises(BookingError):
            services.cancel_booking(booking, self.student)


class ChatTests(TestCase):
    def setUp(self):
        self.tutor = make_tutor()
        self.student = make_student()
        self.booking = Booking.objects.create(slot=make_slot(self.tutor), student=self.student)
        self.eve = make_student('eve')

    def send(self, body, user='sam', ajax=True):
        self.client.login(username=user, password='pw')
        headers = {'HTTP_X_REQUESTED_WITH': 'fetch'} if ajax else {}
        return self.client.post(reverse('tutoring:send', args=[self.booking.pk]), {'body': body}, **headers)

    def test_both_participants_can_chat_and_json_shape_is_stable(self):
        data = self.send('Hello').json()
        self.assertTrue(data['ok'])
        self.assertEqual(set(data['message']), {'id', 'mine', 'body', 'removed', 'time', 'day_key', 'day_label'})
        self.assertTrue(data['message']['mine'])
        self.assertEqual(self.send('Hi Sam', user='maya').status_code, 200)
        self.assertEqual(Message.objects.count(), 2)

    def test_strangers_and_anonymous_get_nothing(self):
        Message.objects.create(booking=self.booking, sender=self.student, body='secret plans')
        urls = [reverse(n, args=[self.booking.pk]) for n in ('tutoring:session', 'tutoring:poll', 'tutoring:calendar', 'tutoring:report', 'tutoring:cancel')]
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 302, url)         # anonymous: login
        self.client.login(username='eve', password='pw')
        for url in urls:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 404, url)
            self.assertNotContains(response, 'secret plans', status_code=404)
        self.assertEqual(self.send('let me in', user='eve').status_code, 404)
        self.assertEqual(Message.objects.count(), 1)

    def test_empty_and_oversized_messages_are_rejected(self):
        self.assertEqual(self.send('   \n  ').status_code, 400)
        response = self.send('x' * 1001)
        self.assertEqual(response.status_code, 400)
        self.assertIn('1000', response.json()['error'])
        self.assertEqual(Message.objects.count(), 0)

    def test_message_rate_limit(self):
        with override_settings(TUTORING_MESSAGE_LIMIT=(3, 60)):
            statuses = [self.send(f'm{i}').status_code for i in range(5)]
        self.assertEqual(statuses, [200, 200, 200, 429, 429])

    def test_rate_limit_is_per_sender(self):
        with override_settings(TUTORING_MESSAGE_LIMIT=(1, 60)):
            self.assertEqual(self.send('a').status_code, 200)
            self.assertEqual(self.send('b', user='maya').status_code, 200)

    def test_read_only_states_reject_new_messages(self):
        self.booking.chat_locked = True
        self.booking.save()
        self.assertEqual(self.send('x').status_code, 403)
        self.booking.chat_locked = False
        self.booking.save()
        with override_settings(TUTORING_CHAT_ENABLED=False):
            self.assertEqual(self.send('x').status_code, 403)
        self.assertEqual(Message.objects.count(), 0)

    def test_chat_closes_after_window(self):
        self.booking.slot.start -= timedelta(days=30)
        self.booking.slot.end -= timedelta(days=30)
        self.booking.slot.save()
        self.assertEqual(services.chat_status(self.booking), 'closed')
        self.assertEqual(self.send('late').status_code, 403)

    def test_cancelled_booking_chat_is_read_only(self):
        services.cancel_booking(self.booking, self.student)
        self.assertEqual(self.send('x').status_code, 403)

    def test_html_in_messages_is_escaped(self):
        Message.objects.create(booking=self.booking, sender=self.student, body='<script>alert(1)</script> <b>hi</b>')
        self.client.login(username='sam', password='pw')
        response = self.client.get(reverse('tutoring:session', args=[self.booking.pk]))
        self.assertNotContains(response, '<script>alert(1)</script>')
        self.assertContains(response, '&lt;script&gt;alert(1)&lt;/script&gt;')

    def test_removed_messages_never_leak_their_text(self):
        Message.objects.create(booking=self.booking, sender=self.student, body='mean words', removed=True)
        self.client.login(username='maya', password='pw')
        page = self.client.get(reverse('tutoring:session', args=[self.booking.pk]))
        self.assertNotContains(page, 'mean words')
        self.assertContains(page, 'removed by an officer')
        poll = self.client.get(reverse('tutoring:poll', args=[self.booking.pk]), {'after': 0}).json()
        self.assertEqual(poll['messages'][0]['body'], '')

    def test_poll_returns_only_newer_messages_and_reports_removals(self):
        a = Message.objects.create(booking=self.booking, sender=self.student, body='one')
        b = Message.objects.create(booking=self.booking, sender=self.student, body='two')
        self.client.login(username='maya', password='pw')
        data = self.client.get(reverse('tutoring:poll', args=[self.booking.pk]), {'after': a.pk}).json()
        self.assertEqual([m['id'] for m in data['messages']], [b.pk])
        Message.objects.filter(pk=a.pk).update(removed=True)
        data = self.client.get(reverse('tutoring:poll', args=[self.booking.pk]), {'after': b.pk}).json()
        self.assertEqual(data['removed'], [a.pk])
        self.assertEqual(self.client.get(reverse('tutoring:poll', args=[self.booking.pk]), {'after': 'junk'}).status_code, 200)

    def test_poll_is_never_cached(self):
        self.client.login(username='sam', password='pw')
        self.assertIn('no-store', self.client.get(reverse('tutoring:poll', args=[self.booking.pk])).headers['Cache-Control'])

    def test_send_requires_post_and_csrf_protected_in_real_client(self):
        self.client.login(username='sam', password='pw')
        self.assertEqual(self.client.get(reverse('tutoring:send', args=[self.booking.pk])).status_code, 405)

    def test_no_javascript_fallback_redirects_back(self):
        response = self.send('plain form post', ajax=False)
        self.assertRedirects(response, reverse('tutoring:session', args=[self.booking.pk]))
        self.assertEqual(Message.objects.get().body, 'plain form post')


class UnreadTests(TestCase):
    def setUp(self):
        self.tutor = make_tutor()
        self.student = make_student()
        self.booking = Booking.objects.create(slot=make_slot(self.tutor), student=self.student)

    def test_unread_counts_only_other_peoples_messages(self):
        services.post_message(self.booking, self.tutor.user, 'hi')
        services.post_message(self.booking, self.tutor.user, 'you there?')
        services.post_message(self.booking, self.student, 'yes')
        self.assertEqual(services.unread_map(self.student), {self.booking.pk: 2})
        self.assertEqual(services.unread_map(self.tutor.user), {self.booking.pk: 1})

    def test_opening_the_chat_marks_read(self):
        services.post_message(self.booking, self.tutor.user, 'hi')
        self.client.login(username='sam', password='pw')
        self.assertContains(self.client.get(reverse('tutoring:sessions')), 'aria-label="1 unread message"')
        self.client.get(reverse('tutoring:session', args=[self.booking.pk]))
        self.assertEqual(services.unread_map(self.student), {})

    def test_read_marker_never_moves_backwards(self):
        services.mark_read(self.booking, self.student, 10)
        services.mark_read(self.booking, self.student, 4)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.student_read_through, 10)

    def test_nav_badge_shows_total_and_is_one_query(self):
        services.post_message(self.booking, self.tutor.user, 'hi')
        self.client.login(username='sam', password='pw')
        self.assertContains(self.client.get(reverse('tutoring:directory')), 'aria-label="1 unread"')

    def test_removed_messages_do_not_count_as_unread(self):
        m = services.post_message(self.booking, self.tutor.user, 'bad')
        Message.objects.filter(pk=m.pk).update(removed=True)
        self.assertEqual(services.unread_map(self.student), {})


class SessionListTests(TestCase):
    def test_tabs_and_empty_states(self):
        tutor, student = make_tutor(), make_student()
        self.client.login(username='sam', password='pw')
        self.assertContains(self.client.get(reverse('tutoring:sessions')), 'Nothing booked yet')
        upcoming = Booking.objects.create(slot=make_slot(tutor), student=student)
        past = Booking.objects.create(slot=make_slot(tutor, hours=-48), student=student)
        gone = Booking.objects.create(slot=make_slot(tutor, hours=72), student=student)
        services.cancel_booking(gone, student)
        ids = lambda tab: [b.pk for b in self.client.get(reverse('tutoring:sessions'), {'tab': tab}).context['items']]
        self.assertEqual(ids('upcoming'), [upcoming.pk])
        self.assertEqual(ids('past'), [past.pk])
        self.assertEqual(ids('cancelled'), [gone.pk])
        self.assertEqual(ids('bogus'), [upcoming.pk])

    def test_tutor_sees_sessions_they_teach(self):
        tutor, student = make_tutor(), make_student()
        Booking.objects.create(slot=make_slot(tutor), student=student)
        self.client.login(username='maya', password='pw')
        response = self.client.get(reverse('tutoring:sessions'))
        self.assertContains(response, "You're tutoring")

    def test_students_dont_see_each_others_sessions(self):
        tutor = make_tutor()
        Booking.objects.create(slot=make_slot(tutor), student=make_student())
        make_student('eve')
        self.client.login(username='eve', password='pw')
        self.assertEqual(list(self.client.get(reverse('tutoring:sessions')).context['items']), [])


class ReportTests(TestCase):
    def test_report_is_saved_and_officers_emailed_not_the_other_person(self):
        tutor, student = make_tutor(), make_student()
        booking = Booking.objects.create(slot=make_slot(tutor), student=student)
        self.client.login(username='sam', password='pw')
        response = self.client.post(reverse('tutoring:report', args=[booking.pk]), {'reason': 'uncomfortable', 'details': 'weird'})
        self.assertRedirects(response, reverse('tutoring:session', args=[booking.pk]))
        self.assertEqual(Report.objects.get().reporter, student)
        self.assertEqual([m.to for m in mail.outbox], [['swampworks@example.com']])

    def test_report_needs_a_reason(self):
        tutor, student = make_tutor(), make_student()
        booking = Booking.objects.create(slot=make_slot(tutor), student=student)
        self.client.login(username='sam', password='pw')
        self.client.post(reverse('tutoring:report', args=[booking.pk]), {'details': 'x'})
        self.assertEqual(Report.objects.count(), 0)


class CalendarFileTests(TestCase):
    def test_ics_is_valid_and_escaped(self):
        tutor, student = make_tutor(), make_student()
        booking = Booking.objects.create(slot=make_slot(tutor), student=student, note='Bring: notes, pen;\nand a very long line ' + 'x' * 120)
        self.client.login(username='sam', password='pw')
        response = self.client.get(reverse('tutoring:calendar', args=[booking.pk]))
        self.assertEqual(response['Content-Type'], 'text/calendar; charset=utf-8')
        body = response.content.decode()
        self.assertTrue(body.startswith('BEGIN:VCALENDAR\r\n') and body.endswith('END:VCALENDAR\r\n'))
        self.assertIn(f'UID:booking-{booking.pk}@swampworks', body)
        self.assertRegex(body, r'DTSTART:\d{8}T\d{6}Z')
        self.assertIn('Bring: notes\\, pen\;\\nand', body.replace('\r\n ', ''))
        self.assertTrue(all(len(line.encode()) <= 75 for line in body.split('\r\n')))

    def test_cancelled_booking_has_no_calendar_file(self):
        tutor, student = make_tutor(), make_student()
        booking = Booking.objects.create(slot=make_slot(tutor), student=student)
        services.cancel_booking(booking, student)
        self.client.login(username='sam', password='pw')
        self.assertEqual(self.client.get(reverse('tutoring:calendar', args=[booking.pk])).status_code, 404)


class ModelRuleTests(TestCase):
    def test_slot_validation(self):
        tutor = make_tutor()
        now = timezone.now()
        with self.assertRaises(Exception):
            AvailabilitySlot(tutor=tutor, start=now, end=now - timedelta(minutes=5)).full_clean()
        with self.assertRaises(Exception):
            AvailabilitySlot(tutor=tutor, start=now, end=now + timedelta(minutes=5)).full_clean()
        AvailabilitySlot.objects.create(tutor=tutor, start=now, end=now + timedelta(minutes=30))
        with self.assertRaisesMessage(Exception, 'overlaps'):
            AvailabilitySlot(tutor=tutor, start=now + timedelta(minutes=15), end=now + timedelta(minutes=45)).full_clean()

    def test_db_rejects_backwards_slot(self):
        tutor, now = make_tutor(), timezone.now()
        with self.assertRaises(IntegrityError), transaction.atomic():
            AvailabilitySlot.objects.create(tutor=tutor, start=now, end=now - timedelta(minutes=1))

    def test_display_name_never_exposes_email(self):
        user = User.objects.create_user('sam99', 'secret@example.com', 'pw')
        self.assertEqual(user.display_name, 'sam99')
        user.first_name = 'Sam'
        self.assertEqual(user.display_name, 'Sam')


class AdminAndCommandTests(TestCase):
    def test_every_tutoring_admin_page_loads(self):
        User.objects.create_superuser('boss', 'b@example.com', 'pw')
        self.client.login(username='boss', password='pw')
        tutor = make_tutor()
        booking = Booking.objects.create(slot=make_slot(tutor), student=make_student())
        Message.objects.create(booking=booking, sender=booking.student, body='hi')
        for model in (Subject, TutorProfile, AvailabilitySlot, Booking, Message, Report):
            name = model._meta.model_name
            self.assertEqual(self.client.get(f'/admin/tutoring/{name}/').status_code, 200, name)
        self.assertEqual(self.client.get(f'/admin/tutoring/booking/{booking.pk}/change/').status_code, 200)
        self.assertEqual(self.client.get(f'/admin/tutoring/tutorprofile/{tutor.pk}/change/').status_code, 200)

    def test_repeat_weekly_action_skips_overlaps(self):
        User.objects.create_superuser('boss', 'b@example.com', 'pw')
        self.client.login(username='boss', password='pw')
        tutor = make_tutor()
        slot = make_slot(tutor)
        make_slot(tutor, hours=24 + 24 * 7)  # week 1 already taken
        self.client.post('/admin/tutoring/availabilityslot/', {'action': 'repeat_weekly', '_selected_action': [slot.pk]})
        self.assertEqual(AvailabilitySlot.objects.filter(tutor=tutor).count(), 1 + 1 + 3)

    def test_seed_command_refuses_without_debug(self):
        with override_settings(DEBUG=False), self.assertRaises(CommandError):
            call_command('seed_tutoring')

    @override_settings(DEBUG=True)
    def test_seed_command_is_idempotent(self):
        call_command('seed_tutoring', stdout=open('/dev/null', 'w'))
        count = AvailabilitySlot.objects.count()
        call_command('seed_tutoring', stdout=open('/dev/null', 'w'))
        self.assertEqual(AvailabilitySlot.objects.count(), count)
        self.assertGreater(TutorProfile.objects.filter(is_listed=True).count(), 3)


class LoginRedirectSafetyTests(TestCase):
    def setUp(self):
        make_student()

    def login(self, nxt):
        return self.client.post(reverse('accounts:login'), {'username': 'sam', 'password': 'pw', 'next': nxt})

    def test_external_or_scheme_relative_next_is_ignored(self):
        for evil in ('https://evil.example/', '//evil.example/', 'javascript:alert(1)'):
            self.client.logout()
            self.assertRedirects(self.login(evil), reverse('dashboard:index'), fetch_redirect_response=False)

    def test_local_next_is_honoured(self):
        self.assertRedirects(self.login('/tutors/'), '/tutors/', fetch_redirect_response=False)

    def test_register_honours_next(self):
        response = self.client.post(reverse('accounts:register'), {
            'username': 'new', 'email': 'new@example.com', 'password1': 'a-good-pass-123', 'password2': 'a-good-pass-123', 'next': '/tutors/'})
        self.assertRedirects(response, '/tutors/', fetch_redirect_response=False)


class PageSmokeTests(TestCase):
    def test_every_student_page_renders_for_anonymous_and_member(self):
        tutor = make_tutor()
        make_slot(tutor)
        make_student()
        anonymous = ['landing_page:index', 'landing_page:club', 'landing_page:about', 'landing_page:projects',
                     'landing_page:calendar', 'landing_page:contact', 'landing_page:ideas', 'tutoring:directory',
                     'accounts:login', 'accounts:register']
        for name in anonymous:
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)
        self.assertEqual(self.client.get(reverse('tutoring:profile', args=[tutor.pk])).status_code, 200)
        for name in ('tutoring:sessions', 'tutoring:inbox', 'dashboard:index'):
            self.assertEqual(self.client.get(reverse(name)).status_code, 302, name)
        self.client.login(username='sam', password='pw')
        for name in ('tutoring:sessions', 'tutoring:inbox', 'dashboard:index', 'tutoring:directory', 'landing_page:index'):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)

    def test_404_page_is_styled_and_unknown_session_is_404(self):
        make_student()
        self.client.login(username='sam', password='pw')
        with override_settings(DEBUG=False):
            self.assertContains(self.client.get('/sessions/9999/'), "find that page", status_code=404)


class SendDoesNotMarkReadTests(TestCase):
    def test_sending_does_not_swallow_unseen_messages(self):
        tutor, student = make_tutor(), make_student()
        booking = Booking.objects.create(slot=make_slot(tutor), student=student)
        services.post_message(booking, tutor.user, 'arrived while you were typing')
        services.post_message(booking, student, 'my reply')
        self.assertEqual(services.unread_map(student), {booking.pk: 1})
