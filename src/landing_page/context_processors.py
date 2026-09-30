from django.conf import settings


def club(request):
    return {
        'CLUB_NAME': settings.CLUB_NAME,
        'CLUB_SCHOOL': settings.CLUB_SCHOOL,
        'CLUB_TAGLINE': settings.CLUB_TAGLINE,
        'CLUB_EMAIL': settings.CLUB_EMAIL,
    }
