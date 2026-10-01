from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone

from landing_page.models import JoinRequest, Meeting, ProjectIdea
from tutoring import services
from tutoring.models import Booking


@login_required
def index(request):
    now = timezone.now()
    unread = services.unread_map(request.user)
    upcoming = list(
        services.bookings_for(request.user)
        .filter(status=Booking.CONFIRMED, slot__end__gte=now).order_by('slot__start')[:4]
    )
    for b in upcoming:
        b.role = b.role_of(request.user)
        b.other_name = b.tutor.display_name if b.role == 'student' else b.student.display_name
        b.unread = unread.get(b.pk, 0)
    return render(request, 'dashboard/index.html', {
        'next_session': upcoming[0] if upcoming else None,
        'later_sessions': upcoming[1:],
        'unread_total': sum(unread.values()),
        'soon_tutors': list(services.tutors_with_availability().filter(open_count__gt=0).order_by('next_open')[:3]),
        'next_meeting': Meeting.objects.filter(date__gte=now).first(),
        'join_count': JoinRequest.objects.count(),
        'idea_count': ProjectIdea.objects.count(),
    })
