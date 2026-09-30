from django.db import models
from django.utils import timezone


class Meeting(models.Model):
    title = models.CharField(max_length=100, default='Club Meeting')
    date = models.DateTimeField()
    location = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['date']

    def __str__(self):
        return f'{self.title} - {self.date:%b %d, %Y}'

    @property
    def is_upcoming(self):
        return self.date >= timezone.now()


class Project(models.Model):
    STATUS_CHOICES = [
        ('planning', 'Planning'),
        ('active', 'In progress'),
        ('done', 'Finished'),
    ]

    title = models.CharField(max_length=100)
    summary = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    lead = models.CharField(max_length=100, blank=True, help_text='Student or officer leading it')
    link = models.URLField(blank=True)
    next_step = models.CharField(max_length=200, blank=True)
    next_step_date = models.DateField(null=True, blank=True)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created']

    def __str__(self):
        return self.title


class JoinRequest(models.Model):
    name = models.CharField(max_length=100)
    email = models.EmailField()
    grade = models.CharField(max_length=20, blank=True)
    message = models.TextField(blank=True)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created']

    def __str__(self):
        return f'{self.name} <{self.email}>'


class ProjectIdea(models.Model):
    SOURCE_CHOICES = [
        ('member', 'Club project idea'),
        ('community', 'Idea for the school or community'),
    ]

    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='member')
    title = models.CharField(max_length=100)
    description = models.TextField()
    name = models.CharField(max_length=100, blank=True)
    email = models.EmailField(blank=True)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created']

    def __str__(self):
        return self.title
