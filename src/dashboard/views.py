from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone

from landing_page.models import JoinRequest, Meeting, ProjectIdea


@login_required
def index(request):
    return render(request, 'dashboard/index.html', {
        'next_meeting': Meeting.objects.filter(date__gte=timezone.now()).first(),
        'join_count': JoinRequest.objects.count(),
        'idea_count': ProjectIdea.objects.count(),
    })
