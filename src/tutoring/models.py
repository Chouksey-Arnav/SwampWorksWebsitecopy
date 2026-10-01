from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.text import slugify


class Subject(models.Model):
    CATEGORY_CHOICES = [
        ('math', 'Math'),
        ('science', 'Science'),
        ('english', 'English & writing'),
        ('cs', 'Computer science'),
        ('languages', 'Languages'),
        ('social', 'Social studies'),
        ('other', 'Other'),
    ]

    name = models.CharField(max_length=60, unique=True)
    slug = models.SlugField(max_length=70, unique=True, blank=True)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='other')

    class Meta:
        ordering = ['category', 'name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class TutorProfile(models.Model):
    """A club member who tutors. Nothing is public until an officer ticks `is_listed`."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='tutor_profile')
    display_name = models.CharField(max_length=60, help_text='What students see. First name and last initial only, e.g. "Maya R."')
    headline = models.CharField(max_length=120, help_text='One line, e.g. "AP Calculus BC and Statistics"')
    bio = models.TextField(max_length=800, blank=True)
    grade_label = models.CharField(max_length=40, blank=True, help_text='e.g. "Senior"')
    subjects = models.ManyToManyField(Subject, related_name='tutors', blank=True)
    location = models.CharField(max_length=100, default='School library', help_text='Where sessions happen')
    is_listed = models.BooleanField(default=False, help_text='Only officers should tick this, after approving the tutor.')
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['display_name']

    def __str__(self):
        return self.display_name

    @property
    def initials(self):
        parts = [p for p in self.display_name.replace('.', ' ').split() if p]
        return ''.join(p[0] for p in parts[:2]).upper() or '?'

    @property
    def first_name(self):
        return self.display_name.split(' ')[0] if self.display_name else ''

    @property
    def slug(self):
        return slugify(self.display_name)


class AvailabilitySlot(models.Model):
    """One bookable block of time. A slot has at most one confirmed booking."""

    MIN_MINUTES, MAX_MINUTES = 15, 120

    tutor = models.ForeignKey(TutorProfile, on_delete=models.CASCADE, related_name='slots')
    start = models.DateTimeField()
    end = models.DateTimeField()
    is_open = models.BooleanField(default=True, help_text='Untick to take this time off the market without deleting it.')

    class Meta:
        ordering = ['start']
        constraints = [
            models.CheckConstraint(condition=Q(end__gt=models.F('start')), name='slot_end_after_start'),
        ]
        indexes = [models.Index(fields=['tutor', 'start'])]

    def __str__(self):
        return f'{self.tutor} {timezone.localtime(self.start):%a %b %d %I:%M %p}'

    @property
    def minutes(self):
        return int((self.end - self.start).total_seconds() // 60)

    def clean(self):
        if self.start and self.end:
            if self.end <= self.start:
                raise ValidationError('A slot must end after it starts.')
            if not self.MIN_MINUTES <= self.minutes <= self.MAX_MINUTES:
                raise ValidationError(f'Slots must be {self.MIN_MINUTES} to {self.MAX_MINUTES} minutes long.')
            if self.tutor_id:
                clash = AvailabilitySlot.objects.filter(tutor_id=self.tutor_id, start__lt=self.end, end__gt=self.start)
                if self.pk:
                    clash = clash.exclude(pk=self.pk)
                if clash.exists():
                    raise ValidationError('This overlaps another slot for the same tutor.')


class Booking(models.Model):
    CONFIRMED, CANCELLED = 'confirmed', 'cancelled'
    STATUS_CHOICES = [(CONFIRMED, 'Confirmed'), (CANCELLED, 'Cancelled')]

    slot = models.ForeignKey(AvailabilitySlot, on_delete=models.PROTECT, related_name='bookings')
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='tutoring_bookings')
    subject = models.ForeignKey(Subject, null=True, blank=True, on_delete=models.SET_NULL, related_name='bookings')
    note = models.TextField(max_length=300, blank=True)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=CONFIRMED)
    cancelled_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    cancelled_at = models.DateTimeField(null=True, blank=True)
    chat_locked = models.BooleanField(default=False, help_text='Officers: tick to make this conversation read-only.')
    # Highest Message id each side has seen. Unread = newer messages from the other person.
    student_read_through = models.PositiveBigIntegerField(default=0, editable=False)
    tutor_read_through = models.PositiveBigIntegerField(default=0, editable=False)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-slot__start']
        constraints = [
            # The double-booking guard. The database enforces it, so two simultaneous requests can't both win.
            models.UniqueConstraint(fields=['slot'], condition=Q(status='confirmed'), name='one_confirmed_booking_per_slot'),
        ]

    def __str__(self):
        return f'{self.student} with {self.tutor} at {self.start:%Y-%m-%d %H:%M}'

    @property
    def tutor(self):
        return self.slot.tutor

    @property
    def start(self):
        return self.slot.start

    @property
    def end(self):
        return self.slot.end

    @property
    def is_confirmed(self):
        return self.status == self.CONFIRMED

    @property
    def is_upcoming(self):
        return self.is_confirmed and self.end >= timezone.now()

    @property
    def is_past(self):
        return self.is_confirmed and self.end < timezone.now()

    @property
    def is_in_progress(self):
        now = timezone.now()
        return self.is_confirmed and self.start <= now <= self.end

    def role_of(self, user):
        if user.pk == self.student_id:
            return 'student'
        if user.pk == self.slot.tutor.user_id:
            return 'tutor'
        return None

    def chat_closes_at(self):
        return self.end + timedelta(days=settings.TUTORING_CHAT_CLOSES_AFTER_DAYS)


class Message(models.Model):
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='+')
    body = models.TextField(max_length=1000)
    created = models.DateTimeField(auto_now_add=True)
    removed = models.BooleanField(default=False, help_text='Officers: hides the text from both people.')

    class Meta:
        ordering = ['id']
        indexes = [models.Index(fields=['booking', 'id'])]

    def __str__(self):
        return f'{self.sender}: {self.body[:40]}'


class Report(models.Model):
    REASON_CHOICES = [
        ('uncomfortable', 'Something made me uncomfortable'),
        ('inappropriate', 'Inappropriate message or behavior'),
        ('no_show', 'The other person did not show up'),
        ('other', 'Something else'),
    ]

    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='reports')
    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='+')
    reason = models.CharField(max_length=20, choices=REASON_CHOICES)
    details = models.TextField(max_length=1000, blank=True)
    resolved = models.BooleanField(default=False)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['resolved', '-created']

    def __str__(self):
        return f'{self.get_reason_display()} (booking {self.booking_id})'
