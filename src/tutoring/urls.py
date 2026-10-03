from django.urls import path

from . import views

app_name = 'tutoring'

urlpatterns = [
    path('tutors/', views.directory, name='directory'),
    path('tutors/<int:pk>/', views.tutor_profile, name='profile'),
    path('book/<int:slot_id>/', views.book, name='book'),
    path('sessions/', views.sessions, name='sessions'),
    path('sessions/<int:pk>/', views.session_detail, name='session'),
    path('sessions/<int:pk>/messages/', views.poll, name='poll'),
    path('sessions/<int:pk>/send/', views.send, name='send'),
    path('sessions/<int:pk>/cancel/', views.cancel, name='cancel'),
    path('sessions/<int:pk>/report/', views.report, name='report'),
    path('sessions/<int:pk>/calendar.ics', views.calendar_file, name='calendar'),
    path('messages/', views.inbox, name='inbox'),
]
