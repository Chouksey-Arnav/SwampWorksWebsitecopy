# Swamp Works Website

Website for the GLHS Swamp Works IT service club: landing page, about, projects, meeting calendar, join form, project idea form, member login, and **peer tutoring** (find a tutor, book a time, chat).

## Run it

    cd src
    python3 -m venv env && source env/bin/activate
    pip install -r requirements.txt
    cp .env.example .env
    python manage.py migrate
    python manage.py createsuperuser   # this is your officer account
    python manage.py runserver

Open http://127.0.0.1:8000. Officers (staff users) add meetings, projects, and see sign-ups and ideas at `/admin/`.

Sign-up emails print to the terminal in development. Set `EMAIL_HOST` in `.env` to send real email.

## Tests

    python manage.py test

## Peer tutoring

Students find a tutor (`/tutors/`), pick an open time, confirm, and get a chat tied to that booking (`/sessions/<id>/`). Everything works without JavaScript; JS adds live chat updates (polling, no websockets, so it runs on Vercel) and retry on failed sends.

**Officer setup (all in `/admin/`)**

1. Create the tutor's normal user account (they can register at `/accounts/register/`).
2. *Tutoring > Tutor profiles > Add*: pick the user, set a display name (**first name + last initial only**), headline, bio and subjects. Tutors are hidden until you tick **Is listed**.
3. Add their open times as *Availability slots* inline on the profile (15 to 120 minutes each). Select slots and use **Repeat selected slots for the next 4 weeks** to avoid retyping.
4. Watch *Reports* (students can report a problem from any chat; officers are also emailed). Use *Bookings > Make chat read-only* or *Messages > Remove* to moderate.

**Safety rules built in:** chat only exists for a confirmed booking; officers can read every conversation and users are told so in the chat; messages are rate limited; a tutor's email is never shown; only first name or username is shown for students; strangers get a 404 for other people's sessions; the double-booking guard is a database constraint.

**Settings** (environment variables, with defaults): `TIME_ZONE` (`America/New_York`), `TUTORING_CHAT_ENABLED` (`True`, the kill switch), `TUTORING_MIN_NOTICE_HOURS` (2), `TUTORING_CANCEL_NOTICE_HOURS` (2), `TUTORING_BOOKING_HORIZON_DAYS` (21), `TUTORING_MAX_UPCOMING_PER_STUDENT` (4), `TUTORING_CHAT_CLOSES_AFTER_DAYS` (7).

**Try it locally with demo data**

    python manage.py seed_tutoring          # adds 8 demo tutors and open times (refuses if DEBUG is off)
    python manage.py seed_tutoring --reset  # wipe demo tutors first
