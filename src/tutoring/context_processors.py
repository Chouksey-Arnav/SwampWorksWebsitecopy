from .services import unread_map


class _LazyUnread:
    """Template calls this at most once per request, and only if a template actually asks."""

    def __init__(self, user):
        self.user = user
        self._value = None

    def __call__(self):
        if self._value is None:
            self._value = sum(unread_map(self.user).values()) if self.user.is_authenticated else 0
        return self._value


def tutoring(request):
    return {'unread_messages': _LazyUnread(request.user)}
