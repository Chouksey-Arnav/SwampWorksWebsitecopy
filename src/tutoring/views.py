from datetime import timedelta
from itertools import groupby

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Exists, F, OuterRef, Q, Subquery
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from . import services
from .forms import BookingForm, ReportForm
from .models import AvailabilitySlot, Booking, Message, Subject, TutorProfile
from .services import BookingError, ChatError
from .templatetags.tutoring_tags import clock, friendly_day

PAGE_SIZE = 12


# --- Finding a tutor --------------------------------------------------------

def directory(request):
    q = request.GET.get('q', '').strip()[:80]
    subject_slug = request.GET.get('subject', '')
    only_open = request.GET.get('open') == '1'
    sort = request.GET.get('sort', 'soonest')

    tutors = services.tutors_with_availability()
    for word in q.split()[:5]:
        tutors = tutors.filter(
            Q(display_name__icontains=word) | Q(headline__icontains=word) | Q(bio__icontains=word)
            | Exists(Subject.objects.filter(tutors=OuterRef('pk'), name__icontains=word))
        )
    if subject_slug:
        tutors = tutors.filter(subjects__slug=subject_slug)
    if only_open:
        tutors = tutors.filter(open_count__gt=0)
    tutors = tutors.order_by('display_name') if sort == 'name' else tutors.order_by(F('next_open').asc(nulls_last=True), 'display_name')

    # Subject chips: only subjects somebody actually tutors, with how many tutors.
    subjects = list(
        Subject.objects.filter(tutors__is_listed=True).annotate(n=Count('tutors', filter=Q(tutors__is_listed=True))).order_by('name')
    )
    active_subject = next((s for s in subjects if s.slug == subject_slug), None)

    page = Paginator(tutors, PAGE_SIZE).get_page(request.GET.get('page'))
    return render(request, 'tutoring/directory.html', {
        'page': page,
        'q': q,
        'subjects': subjects,
        'active_subject': active_subject,
        'only_open': only_open,
        'sort': 'name' if sort == 'name' else 'soonest',
        'filtered': bool(q or active_subject or only_open),
        'total_tutors': TutorProfile.objects.filter(is_listed=True).count(),
    })


def tutor_profile(request, pk):
    tutor = get_object_or_404(TutorProfile.objects.prefetch_related('subjects').select_related('user'), pk=pk)
    is_owner = request.user.is_authenticated and tutor.user_id == request.user.pk
    if not tutor.is_listed and not (request.user.is_staff or is_owner):
        raise Http404

    slots = list(services.open_slots().filter(tutor=tutor).order_by('start')) if tutor.is_listed else []
    days = [
        {'date': day, 'first': items[0].start, 'slots': items}
        for day, items in ((d, list(g)) for d, g in groupby(slots, key=lambda s: timezone.localtime(s.start).date()))
    ]
    upcoming_with = None
    if request.user.is_authenticated:
        upcoming_with = Booking.objects.filter(
            student=request.user, slot__tutor=tutor, status=Booking.CONFIRMED, slot__end__gte=timezone.now(),
        ).select_related('slot').order_by('slot__start').first()
    return render(request, 'tutoring/profile.html', {
        'tutor': tutor,
        'days': days,
        'visible_days': days[:5],
        'more_days': days[5:],
        'slot_total': len(slots),
        'is_owner': is_owner,
        'preview': not tutor.is_listed,
        'upcoming_with': upcoming_with,
        'horizon': settings.TUTORING_BOOKING_HORIZON_DAYS,
    })


# --- Booking ----------------------------------------------------------------

@login_required
def book(request, slot_id):
    slot = get_object_or_404(AvailabilitySlot.objects.select_related('tutor__user'), pk=slot_id)
    tutor = slot.tutor
    if not services.open_slots().filter(pk=slot.pk).exists():
        messages.error(request, 'That time was just taken or is no longer available. Pick another.')
        return redirect('tutoring:profile', pk=tutor.pk)
    if tutor.user_id == request.user.pk:
        messages.error(request, "You can't book a session with yourself.")
        return redirect('tutoring:profile', pk=tutor.pk)

    form = BookingForm(request.POST or None, tutor=tutor)
    if request.method == 'POST' and form.is_valid():
        try:
            booking = services.book_slot(request.user, slot.pk, form.cleaned_data['subject'], form.cleaned_data['note'])
        except BookingError as error:
            messages.error(request, str(error))
            return redirect('tutoring:profile', pk=tutor.pk)
        messages.success(request, f"You're booked with {tutor.display_name}. Say hi below.")
        return redirect('tutoring:session', pk=booking.pk)

    return render(request, 'tutoring/book.html', {
        'form': form,
        'slot': slot,
        'tutor': tutor,
        'cancel_hours': settings.TUTORING_CANCEL_NOTICE_HOURS,
    })


# --- Sessions ---------------------------------------------------------------

def _booking_or_404(request, pk):
    return get_object_or_404(services.bookings_for(request.user), pk=pk)


def _decorate(bookings, user, unread):
    """Attach what a list row needs: the other person, and unread count."""
    for b in bookings:
        b.role = b.role_of(user)
        b.other_name = b.tutor.display_name if b.role == 'student' else b.student.display_name
        b.unread = unread.get(b.pk, 0)
    return bookings


@login_required
def sessions(request):
    now = timezone.now()
    base = services.bookings_for(request.user)
    groups = {
        'upcoming': base.filter(status=Booking.CONFIRMED, slot__end__gte=now).order_by('slot__start'),
        'past': base.filter(status=Booking.CONFIRMED, slot__end__lt=now).order_by('-slot__start'),
        'cancelled': base.filter(status=Booking.CANCELLED).order_by('-slot__start'),
    }
    tab = request.GET.get('tab')
    if tab not in groups:
        tab = 'upcoming'
    counts = {name: qs.count() for name, qs in groups.items()}
    items = _decorate(list(groups[tab]), request.user, services.unread_map(request.user))
    return render(request, 'tutoring/sessions.html', {
        'tab': tab,
        'counts': counts,
        'items': items,
        'is_tutor': hasattr(request.user, 'tutor_profile'),
    })


def _serialize(message, user):
    local = timezone.localtime(message.created)
    return {
        'id': message.id,
        'mine': message.sender_id == user.pk,
        'body': '' if message.removed else message.body,
        'removed': message.removed,
        'time': clock(message.created),
        'day_key': local.date().isoformat(),
        'day_label': friendly_day(message.created),
    }


def conversations(user, current=None):
    """The inbox rail: recent confirmed bookings, newest activity first."""
    now = timezone.now()
    last = Message.objects.filter(booking=OuterRef('pk')).order_by('-id')
    rows = list(
        services.bookings_for(user)
        .filter(status=Booking.CONFIRMED, slot__end__gte=now - timedelta(days=settings.TUTORING_CHAT_CLOSES_AFTER_DAYS))
        .annotate(last_body=Subquery(last.values('body')[:1]), last_at=Subquery(last.values('created')[:1]),
                  last_sender=Subquery(last.values('sender_id')[:1]), last_removed=Subquery(last.values('removed')[:1]))
    )
    unread = services.unread_map(user)
    _decorate(rows, user, unread)
    for b in rows:
        b.sort_key = b.last_at or b.created
        if b.last_at is None:
            b.preview = 'No messages yet. Say hi.'
        elif b.last_removed:
            b.preview = 'Message removed by an officer'
        else:
            b.preview = ('You: ' if b.last_sender == user.pk else '') + b.last_body.replace('\n', ' ')[:90]
        b.current = current is not None and b.pk == current
    rows.sort(key=lambda b: b.sort_key, reverse=True)
    return rows[:50]


@login_required
def session_detail(request, pk):
    booking = _booking_or_404(request, pk)
    role = booking.role_of(request.user)
    latest = list(booking.messages.order_by('-id')[:200])[::-1]
    if latest:
        services.mark_read(booking, request.user, latest[-1].id)
    status = services.chat_status(booking)
    other_name = booking.tutor.display_name if role == 'student' else booking.student.display_name
    return render(request, 'tutoring/session.html', {
        'booking': booking,
        'role': role,
        'other_name': other_name,
        'thread': [_serialize(m, request.user) for m in latest],
        'last_id': latest[-1].id if latest else 0,
        'chat_status': status,
        'chat_status_text': services.CHAT_STATUS_TEXT[status],
        'cancel_problem': services.cancel_problem(booking, request.user),
        'cancel_deadline': services.cancel_deadline(booking),
        'conversations': conversations(request.user, current=booking.pk),
    })


@login_required
@require_GET
def poll(request, pk):
    booking = _booking_or_404(request, pk)
    try:
        after = max(int(request.GET.get('after', 0)), 0)
    except ValueError:
        after = 0
    fresh = list(booking.messages.filter(id__gt=after).order_by('id')[:100])
    if fresh:
        services.mark_read(booking, request.user, fresh[-1].id)
    # Tell open tabs about messages an officer has removed since they were drawn.
    removed = list(booking.messages.filter(removed=True, id__lte=after).order_by('-id').values_list('id', flat=True)[:100])
    status = services.chat_status(booking)
    response = JsonResponse({
        'messages': [_serialize(m, request.user) for m in fresh],
        'removed': removed,
        'status': status,
        'status_text': services.CHAT_STATUS_TEXT[status],
    })
    response['Cache-Control'] = 'no-store'
    return response


@login_required
@require_POST
def send(request, pk):
    booking = _booking_or_404(request, pk)
    wants_json = request.headers.get('X-Requested-With') == 'fetch'
    try:
        message = services.post_message(booking, request.user, request.POST.get('body', ''))
    except ChatError as error:
        if wants_json:
            return JsonResponse({'ok': False, 'error': str(error)}, status=error.status)
        messages.error(request, str(error))
        return redirect('tutoring:session', pk=booking.pk)
    if wants_json:
        return JsonResponse({'ok': True, 'message': _serialize(message, request.user)})
    return redirect('tutoring:session', pk=booking.pk)


@login_required
def cancel(request, pk):
    booking = _booking_or_404(request, pk)
    problem = services.cancel_problem(booking, request.user)
    if request.method == 'POST':
        try:
            services.cancel_booking(booking, request.user)
        except BookingError as error:
            messages.error(request, str(error))
            return redirect('tutoring:session', pk=booking.pk)
        messages.success(request, 'Session cancelled. We let the other person know.')
        return redirect('tutoring:sessions')
    other_name = booking.tutor.display_name if booking.role_of(request.user) == 'student' else booking.student.display_name
    return render(request, 'tutoring/cancel.html', {
        'booking': booking, 'problem': problem, 'other_name': other_name,
    })


@login_required
def report(request, pk):
    booking = _booking_or_404(request, pk)
    form = ReportForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        item = form.save(commit=False)
        item.booking, item.reporter = booking, request.user
        item.save()
        services.notify_report(item)
        messages.success(request, 'Thank you. An officer will look at this.')
        return redirect('tutoring:session', pk=booking.pk)
    other_name = booking.tutor.display_name if booking.role_of(request.user) == 'student' else booking.student.display_name
    return render(request, 'tutoring/report.html', {'form': form, 'booking': booking, 'other_name': other_name})


@login_required
@require_GET
def calendar_file(request, pk):
    booking = _booking_or_404(request, pk)
    if not booking.is_confirmed:
        raise Http404
    response = HttpResponse(services.booking_ics(booking, request.user), content_type='text/calendar; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="tutoring-{booking.pk}.ics"'
    return response


@login_required
def inbox(request):
    return render(request, 'tutoring/inbox.html', {'conversations': conversations(request.user)})
