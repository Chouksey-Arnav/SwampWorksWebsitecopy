from datetime import timedelta

from django.contrib import admin, messages
from django.db.models import Count, Q
from django.utils import timezone

from .models import AvailabilitySlot, Booking, Message, Report, Subject, TutorProfile


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ('name', 'category')
    list_filter = ('category',)
    search_fields = ('name',)
    prepopulated_fields = {'slug': ('name',)}


class SlotInline(admin.TabularInline):
    model = AvailabilitySlot
    extra = 2
    fields = ('start', 'end', 'is_open')
    ordering = ('start',)


@admin.register(TutorProfile)
class TutorProfileAdmin(admin.ModelAdmin):
    list_display = ('display_name', 'user', 'is_listed', 'subject_list', 'upcoming_slots')
    list_filter = ('is_listed', 'subjects')
    list_editable = ('is_listed',)
    search_fields = ('display_name', 'user__username', 'user__email')
    autocomplete_fields = ('user',)
    filter_horizontal = ('subjects',)
    inlines = [SlotInline]
    actions = ['list_tutors', 'unlist_tutors']

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related('subjects').annotate(
            _upcoming=Count('slots', filter=Q(slots__start__gte=timezone.now(), slots__is_open=True)))

    @admin.display(description='Subjects')
    def subject_list(self, obj):
        return ', '.join(s.name for s in obj.subjects.all())

    @admin.display(description='Open slots ahead', ordering='_upcoming')
    def upcoming_slots(self, obj):
        return obj._upcoming

    @admin.action(description='List selected tutors publicly')
    def list_tutors(self, request, queryset):
        self.message_user(request, f'{queryset.update(is_listed=True)} tutor(s) now visible to students.')

    @admin.action(description='Hide selected tutors from students')
    def unlist_tutors(self, request, queryset):
        self.message_user(request, f'{queryset.update(is_listed=False)} tutor(s) hidden.')


@admin.register(AvailabilitySlot)
class AvailabilitySlotAdmin(admin.ModelAdmin):
    list_display = ('tutor', 'start', 'end', 'is_open', 'taken')
    list_filter = ('is_open', 'tutor')
    date_hierarchy = 'start'
    actions = ['repeat_weekly']

    @admin.display(boolean=True, description='Booked')
    def taken(self, obj):
        return obj.bookings.filter(status=Booking.CONFIRMED).exists()

    @admin.action(description='Repeat selected slots for the next 4 weeks')
    def repeat_weekly(self, request, queryset):
        made = skipped = 0
        for slot in queryset:
            for week in range(1, 5):
                copy = AvailabilitySlot(tutor=slot.tutor, start=slot.start + timedelta(weeks=week),
                                        end=slot.end + timedelta(weeks=week))
                clash = AvailabilitySlot.objects.filter(tutor=slot.tutor, start__lt=copy.end, end__gt=copy.start).exists()
                if clash:
                    skipped += 1
                else:
                    copy.save()
                    made += 1
        self.message_user(request, f'Created {made} slot(s); skipped {skipped} that overlapped existing ones.',
                          messages.SUCCESS if made else messages.WARNING)


class MessageInline(admin.TabularInline):
    """Officers can read every conversation. Students and tutors are told this in the chat."""
    model = Message
    extra = 0
    can_delete = False
    fields = ('created', 'sender', 'body', 'removed')
    readonly_fields = ('created', 'sender', 'body')

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'status', 'subject', 'chat_locked', 'created')
    list_filter = ('status', 'chat_locked')
    search_fields = ('student__username', 'student__email', 'slot__tutor__display_name')
    raw_id_fields = ('slot', 'student')
    readonly_fields = ('cancelled_by', 'cancelled_at', 'created')
    inlines = [MessageInline]
    actions = ['lock_chat', 'unlock_chat']

    @admin.action(description='Make chat read-only')
    def lock_chat(self, request, queryset):
        self.message_user(request, f'{queryset.update(chat_locked=True)} conversation(s) locked.')

    @admin.action(description='Re-open chat')
    def unlock_chat(self, request, queryset):
        self.message_user(request, f'{queryset.update(chat_locked=False)} conversation(s) re-opened.')


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ('created', 'sender', 'short', 'booking', 'removed')
    list_filter = ('removed',)
    search_fields = ('body', 'sender__username')
    readonly_fields = ('booking', 'sender', 'body', 'created')
    actions = ['remove_messages', 'restore_messages']

    @admin.display(description='Message')
    def short(self, obj):
        return obj.body[:80]

    def has_add_permission(self, request):
        return False

    @admin.action(description='Remove selected messages (hidden from both people)')
    def remove_messages(self, request, queryset):
        self.message_user(request, f'{queryset.update(removed=True)} message(s) removed.')

    @admin.action(description='Restore selected messages')
    def restore_messages(self, request, queryset):
        self.message_user(request, f'{queryset.update(removed=False)} message(s) restored.')


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ('created', 'reason', 'reporter', 'booking', 'resolved')
    list_filter = ('resolved', 'reason')
    readonly_fields = ('booking', 'reporter', 'reason', 'details', 'created')
    actions = ['mark_resolved']

    def has_add_permission(self, request):
        return False

    @admin.action(description='Mark selected reports resolved')
    def mark_resolved(self, request, queryset):
        self.message_user(request, f'{queryset.update(resolved=True)} report(s) resolved.')
