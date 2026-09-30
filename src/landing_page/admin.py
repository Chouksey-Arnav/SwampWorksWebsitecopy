from django.contrib import admin

from .models import JoinRequest, Meeting, Project, ProjectIdea


@admin.register(Meeting)
class MeetingAdmin(admin.ModelAdmin):
    list_display = ('title', 'date', 'location')


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ('title', 'status', 'lead', 'next_step_date')
    list_filter = ('status',)


@admin.register(JoinRequest)
class JoinRequestAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'grade', 'created')


@admin.register(ProjectIdea)
class ProjectIdeaAdmin(admin.ModelAdmin):
    list_display = ('title', 'source', 'name', 'created')
    list_filter = ('source',)
