from django.urls import path

from . import views

app_name = 'landing_page'

urlpatterns = [
    path('', views.index, name='index'),
    path('club/', views.club, name='club'),
    path('about/', views.about, name='about'),
    path('projects/', views.projects, name='projects'),
    path('calendar/', views.calendar, name='calendar'),
    path('join/', views.contact, name='contact'),
    path('ideas/', views.ideas, name='ideas'),
]
