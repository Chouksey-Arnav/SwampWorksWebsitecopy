from django.conf import settings
from django.contrib import messages
from django.core.mail import send_mail
from django.shortcuts import redirect, render
from django.utils import timezone

from django.db.models import Count, Q

from tutoring.models import Subject
from tutoring.services import tutors_with_availability

from .forms import IdeaForm, JoinForm
from .models import Meeting, Project


def index(request):
    bookable = tutors_with_availability().filter(open_count__gt=0).order_by('next_open')
    return render(request, 'landing_page/index.html', {
        'next_meeting': Meeting.objects.filter(date__gte=timezone.now()).first(),
        'projects': Project.objects.exclude(status='done')[:3],
        'soon_tutors': list(bookable[:3]),
        'popular_subjects': Subject.objects.filter(tutors__is_listed=True)
        .annotate(n=Count('tutors', filter=Q(tutors__is_listed=True))).order_by('-n', 'name')[:4],
    })


def club(request):
    return render(request, 'landing_page/club.html', {
        'next_meeting': Meeting.objects.filter(date__gte=timezone.now()).first(),
    })


def about(request):
    return render(request, 'landing_page/about.html')


def projects(request):
    return render(request, 'landing_page/projects.html', {
        'active': Project.objects.exclude(status='done'),
        'finished': Project.objects.filter(status='done'),
    })


def calendar(request):
    now = timezone.now()
    return render(request, 'landing_page/calendar.html', {
        'upcoming': Meeting.objects.filter(date__gte=now),
        'past': Meeting.objects.filter(date__lt=now).order_by('-date')[:5],
    })


def contact(request):
    form = JoinForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        join = form.save()
        # Let the officers know someone signed up. Prints to the terminal in dev.
        send_mail(
            f'New member request: {join.name}',
            f'{join.name} ({join.email}), grade {join.grade or "n/a"}\n\n{join.message}',
            settings.DEFAULT_FROM_EMAIL,
            [settings.CLUB_EMAIL],
            fail_silently=True,
        )
        messages.success(request, "Thanks! We got your info and will email you about the next meeting.")
        return redirect('landing_page:contact')
    return render(request, 'landing_page/contact.html', {'form': form})


def ideas(request):
    form = IdeaForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Idea submitted. Thank you!')
        return redirect('landing_page:ideas')
    return render(request, 'landing_page/ideas.html', {'form': form})
