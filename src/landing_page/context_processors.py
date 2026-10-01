from django.conf import settings

NAV_BY_URL = {
    'landing_page:index': 'home', 'dashboard:index': 'home',
    'tutoring:directory': 'tutors', 'tutoring:profile': 'tutors', 'tutoring:book': 'tutors',
    'tutoring:sessions': 'sessions', 'tutoring:cancel': 'sessions', 'tutoring:report': 'sessions',
    'tutoring:inbox': 'messages', 'tutoring:session': 'messages',
    'landing_page:club': 'club', 'landing_page:about': 'club', 'landing_page:projects': 'club',
    'landing_page:calendar': 'club', 'landing_page:ideas': 'club', 'landing_page:contact': 'club',
    'accounts:login': 'login', 'accounts:register': 'login',
}


def club(request):
    match = getattr(request, 'resolver_match', None)
    return {
        'CLUB_NAME': settings.CLUB_NAME,
        'CLUB_SCHOOL': settings.CLUB_SCHOOL,
        'CLUB_TAGLINE': settings.CLUB_TAGLINE,
        'CLUB_EMAIL': settings.CLUB_EMAIL,
        'NAV': NAV_BY_URL.get(match.view_name if match else '', ''),
    }
