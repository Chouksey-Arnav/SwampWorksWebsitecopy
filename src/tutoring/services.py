"""Business rules for tutoring. Views call these; nothing here knows about HTTP."""
from datetime import timedelta, timezone as dt_timezone

from django.conf import settings
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.db.models import Count, F, Q
from django.utils import timezone

from .models import AvailabilitySlot, Booking, Message


class BookingError(Exception):
    """Raised with a message that is safe to show the student."""


class ChatError(Exception):
    """Raised with a message that is safe to show the sender."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


# --- Availability -----------------------------------------------------------

def bookable_window(now=None):
    now = now or timezone.now()
    return (
        now + timedelta(hours=settings.TUTORING_MIN_NOTICE_HOURS),
        now + timedelta(days=settings.TUTORING_BOOKING_HORIZON_DAYS),
    )


def open_slots(now=None):
    """Slots a student could book right now: open, in the window, and not already taken."""
    earliest, latest = bookable_window(now)
    return (
        AvailabilitySlot.objects
        .filter(is_open=True, tutor__is_listed=True, start__gte=earliest, start__lte=latest)
        .exclude(bookings__status=Booking.CONFIRMED)
    )


# --- Booking ----------------------------------------------------------------

def book_slot(student, slot_id, subject=None, note=''):
    """Create a confirmed booking or raise BookingError. Safe against two people grabbing one slot."""
    now = timezone.now()
    with transaction.atomic():
        try:
            slot = AvailabilitySlot.objects.select_related('tutor__user').select_for_update(of=('self',)).get(pk=slot_id)
        except AvailabilitySlot.DoesNotExist:
            raise BookingError('That time no longer exists.')

        earliest, latest = bookable_window(now)
        if not (slot.is_open and slot.tutor.is_listed) or slot.start < earliest or slot.start > latest:
            raise BookingError('That time is no longer available.')
        if slot.tutor.user_id == student.pk:
            raise BookingError("You can't book a session with yourself.")
        if subject is not None and not slot.tutor.subjects.filter(pk=subject.pk).exists():
            raise BookingError(f'{slot.tutor.first_name} does not tutor that subject.')

        mine = Booking.objects.filter(student=student, status=Booking.CONFIRMED, slot__end__gte=now)
        if mine.count() >= settings.TUTORING_MAX_UPCOMING_PER_STUDENT:
            raise BookingError(
                f'You already have {settings.TUTORING_MAX_UPCOMING_PER_STUDENT} upcoming sessions. '
                'Finish or cancel one before booking another.'
            )
        if mine.filter(slot__start__lt=slot.end, slot__end__gt=slot.start).exists():
            raise BookingError('You already have a session at that time.')

        try:
            with transaction.atomic():
                booking = Booking.objects.create(slot=slot, student=student, subject=subject, note=note.strip())
        except IntegrityError:
            # Lost the race: someone else confirmed this slot between our check and our insert.
            raise BookingError('Someone just booked that time. Pick another.')

    notify_booked(booking)
    return booking


def cancel_deadline(booking):
    return booking.start - timedelta(hours=settings.TUTORING_CANCEL_NOTICE_HOURS)


def cancel_problem(booking, user, now=None):
    """Why `user` can't cancel right now, or None if they can."""
    now = now or timezone.now()
    role = booking.role_of(user)
    if role is None:
        return 'Not your session.'
    if not booking.is_confirmed:
        return 'This session is already cancelled.'
    if booking.start <= now:
        return 'This session has already started.'
    if role == 'student' and now > cancel_deadline(booking):
        return (
            f'Students can cancel up to {settings.TUTORING_CANCEL_NOTICE_HOURS} hours before. '
            'Message your tutor instead.'
        )
    return None


def cancel_booking(booking, user):
    problem = cancel_problem(booking, user)
    if problem:
        raise BookingError(problem)
    role = booking.role_of(user)
    with transaction.atomic():
        booking.status = Booking.CANCELLED
        booking.cancelled_by = user
        booking.cancelled_at = timezone.now()
        booking.save(update_fields=['status', 'cancelled_by', 'cancelled_at'])
        if role == 'tutor':
            # The tutor pulled out, so don't offer this time to anyone else.
            AvailabilitySlot.objects.filter(pk=booking.slot_id).update(is_open=False)
    notify_cancelled(booking, user)
    return booking


# --- Chat -------------------------------------------------------------------

def chat_status(booking, now=None):
    """'open' or the reason the thread is read-only."""
    now = now or timezone.now()
    if not settings.TUTORING_CHAT_ENABLED:
        return 'disabled'
    if not booking.is_confirmed:
        return 'cancelled'
    if booking.chat_locked:
        return 'locked'
    if now > booking.chat_closes_at():
        return 'closed'
    return 'open'


CHAT_STATUS_TEXT = {
    'open': '',
    'disabled': 'Chat is switched off for now. Officers will turn it back on.',
    'cancelled': 'This session was cancelled, so the conversation is read-only.',
    'locked': 'An officer has made this conversation read-only.',
    'closed': 'This conversation has closed. Book another session to keep talking.',
}


def clean_body(raw):
    body = (raw or '').replace('\r\n', '\n').replace('\r', '\n').strip()
    while '\n\n\n' in body:
        body = body.replace('\n\n\n', '\n\n')
    return body


def post_message(booking, sender, raw_body):
    if booking.role_of(sender) is None:
        raise ChatError('Not your conversation.', status=404)
    status = chat_status(booking)
    if status != 'open':
        raise ChatError(CHAT_STATUS_TEXT[status], status=403)
    body = clean_body(raw_body)
    if not body:
        raise ChatError('Write something first.')
    if len(body) > 1000:
        raise ChatError(f'That message is {len(body)} characters. The limit is 1000.')
    limit, seconds = settings.TUTORING_MESSAGE_LIMIT
    recent = Message.objects.filter(sender=sender, created__gte=timezone.now() - timedelta(seconds=seconds)).count()
    if recent >= limit:
        raise ChatError('You are sending messages very fast. Give it a few seconds.', status=429)
    # Deliberately no mark_read here: sending doesn't prove the sender has seen earlier messages.
    return Message.objects.create(booking=booking, sender=sender, body=body)


def mark_read(booking, user, through_id):
    role = booking.role_of(user)
    field = {'student': 'student_read_through', 'tutor': 'tutor_read_through'}.get(role)
    if not field or through_id <= getattr(booking, field):
        return
    # Update only if it moves forward, so two open tabs can't rewind each other.
    Booking.objects.filter(pk=booking.pk, **{f'{field}__lt': through_id}).update(**{field: through_id})
    setattr(booking, field, through_id)


def unread_map(user):
    """{booking_id: unread message count} for every booking the user is part of."""
    counts = {}
    as_student = (
        Message.objects.filter(booking__student=user, booking__status=Booking.CONFIRMED,
                               id__gt=F('booking__student_read_through'), removed=False)
        .exclude(sender=user).values('booking_id').annotate(n=Count('id'))
    )
    as_tutor = (
        Message.objects.filter(booking__slot__tutor__user=user, booking__status=Booking.CONFIRMED,
                               id__gt=F('booking__tutor_read_through'), removed=False)
        .exclude(sender=user).values('booking_id').annotate(n=Count('id'))
    )
    for row in list(as_student) + list(as_tutor):
        counts[row['booking_id']] = counts.get(row['booking_id'], 0) + row['n']
    return counts


def bookings_for(user):
    """Every booking the user is part of, as student or as tutor."""
    return (
        Booking.objects.filter(Q(student=user) | Q(slot__tutor__user=user))
        .select_related('slot__tutor__user', 'student', 'subject')
    )


# --- Email ------------------------------------------------------------------

def _mail(user, subject, body):
    if user.email:
        send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [user.email], fail_silently=True)


def _when(booking):
    start = timezone.localtime(booking.start)
    return f'{start:%A, %B %-d at %-I:%M %p}'


def notify_booked(booking):
    when, tutor, student = _when(booking), booking.tutor, booking.student
    topic = booking.subject.name if booking.subject else 'general help'
    _mail(student, f'Booked: {tutor.display_name}, {when}',
          f'You are booked with {tutor.display_name} on {when}.\nTopic: {topic}\nWhere: {tutor.location}\n\n'
          'Chat with your tutor from your Sessions page. Officers can read tutoring conversations.')
    _mail(tutor.user, f'New session: {student.display_name}, {when}',
          f'{student.display_name} booked you on {when}.\nTopic: {topic}\n'
          + (f'Note: {booking.note}\n' if booking.note else ''))


def notify_cancelled(booking, by):
    when = _when(booking)
    other = booking.tutor.user if by.pk == booking.student_id else booking.student
    who = booking.student.display_name if by.pk == booking.student_id else booking.tutor.display_name
    _mail(other, f'Cancelled: session on {when}', f'{who} cancelled the session on {when}.')


def notify_report(report):
    b = report.booking
    send_mail(
        f'Tutoring report: {report.get_reason_display()}',
        f'Reporter: {report.reporter} (id {report.reporter_id})\nBooking: {b.pk} - {b.student} with {b.tutor}\n'
        f'Reason: {report.get_reason_display()}\n\n{report.details}\n\nReview it in the admin under Tutoring > Reports.',
        settings.DEFAULT_FROM_EMAIL, [settings.CLUB_EMAIL], fail_silently=True,
    )


# --- Calendar export --------------------------------------------------------

def _ics_escape(text):
    return text.replace('\\', '\\\\').replace(';', '\\;').replace(',', '\\,').replace('\r', '').replace('\n', '\\n')


def _fold(line):
    """RFC 5545: lines over 75 octets are folded with CRLF + space."""
    raw, out = line.encode('utf-8'), []
    while len(raw) > 75:
        cut = 75
        while raw[cut] & 0xC0 == 0x80:  # don't split a multi-byte character
            cut -= 1
        out.append(raw[:cut].decode('utf-8'))
        raw = b' ' + raw[cut:]
    out.append(raw.decode('utf-8'))
    return '\r\n'.join(out)


def booking_ics(booking, viewer):
    stamp = '%Y%m%dT%H%M%SZ'
    utc = dt_timezone.utc
    start, end = booking.start.astimezone(utc), booking.end.astimezone(utc)
    other = booking.tutor.display_name if viewer.pk == booking.student_id else booking.student.display_name
    topic = booking.subject.name if booking.subject else 'Tutoring'
    lines = [
        'BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Swamp Works//Tutoring//EN', 'CALSCALE:GREGORIAN', 'METHOD:PUBLISH',
        'BEGIN:VEVENT',
        f'UID:booking-{booking.pk}@swampworks',
        f'DTSTAMP:{timezone.now().astimezone(utc).strftime(stamp)}',
        f'DTSTART:{start.strftime(stamp)}',
        f'DTEND:{end.strftime(stamp)}',
        f'SUMMARY:{_ics_escape(f"{topic} with {other}")}',
        f'LOCATION:{_ics_escape(booking.tutor.location)}',
        f'DESCRIPTION:{_ics_escape(booking.note)}' if booking.note else None,
        'END:VEVENT', 'END:VCALENDAR',
    ]
    return '\r\n'.join(_fold(line) for line in lines if line) + '\r\n'


# --- Directory queries ------------------------------------------------------

def tutors_with_availability(now=None):
    """Listed tutors annotated with `next_open` (soonest bookable start) and `open_count`."""
    from django.db.models import OuterRef, Subquery
    from django.db.models.functions import Coalesce

    from .models import TutorProfile

    slots = open_slots(now).filter(tutor=OuterRef('pk'))
    return (
        TutorProfile.objects.filter(is_listed=True)
        .prefetch_related('subjects')
        .annotate(
            next_open=Subquery(slots.order_by('start').values('start')[:1]),
            open_count=Coalesce(Subquery(slots.order_by().values('tutor').annotate(n=Count('pk')).values('n')), 0),
        )
    )
