# Swamp Works Website

Website for the GLHS Swamp Works IT service club: landing page, about, projects, meeting calendar, join form, project idea form, and member login.

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
