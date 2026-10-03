from django import template
from django.utils import timezone

register = template.Library()


@register.simple_tag(takes_context=True)
def qs(context, **changes):
    """Current query string with some keys changed. Empty value removes the key. Changing a filter resets paging."""
    params = context['request'].GET.copy()
    for key, value in changes.items():
        if value in (None, ''):
            params.pop(key, None)
        else:
            params[key] = value
    if 'page' not in changes:
        params.pop('page', None)
    encoded = params.urlencode()
    return f'?{encoded}' if encoded else '?'


@register.filter
def hue(text):
    """Stable 0-359 hue for a name, so every tutor keeps the same avatar colour."""
    return sum(ord(c) * (i + 1) for i, c in enumerate(str(text))) % 360


@register.filter
def initials_of(name):
    parts = [p for p in str(name).replace('.', ' ').split() if p]
    return ''.join(p[0] for p in parts[:2]).upper() or '?'


@register.filter
def friendly_day(value):
    """'Today', 'Tomorrow', or 'Tue, Oct 6' in the site time zone."""
    day = timezone.localtime(value).date()
    today = timezone.localdate()
    if day == today:
        return 'Today'
    if (day - today).days == 1:
        return 'Tomorrow'
    return f'{day:%a, %b} {day.day}'


@register.filter
def clock(value):
    """'3:30 PM' with no leading zero, in the site time zone."""
    local = timezone.localtime(value)
    return f'{local.hour % 12 or 12}:{local:%M} {local:%p}'


@register.filter
def duration(minutes):
    minutes = int(minutes)
    if minutes < 60:
        return f'{minutes} min'
    hours, rest = divmod(minutes, 60)
    return f'{hours} hr' + (f' {rest} min' if rest else '')
