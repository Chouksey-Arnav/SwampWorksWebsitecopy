from django.contrib.auth import authenticate, login, logout
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .forms import CustomUserCreationForm


def _next_url(request):
    """Where to go after login/register: ?next= if it points at this site, else the dashboard."""
    target = request.POST.get('next') or request.GET.get('next') or ''
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return target
    return ''


def login_view(request):
    next_url = _next_url(request)
    if request.user.is_authenticated:
        return redirect(next_url or 'dashboard:index')

    if request.method == 'POST':
        user = authenticate(
            request,
            username=request.POST.get('username', ''),
            password=request.POST.get('password', ''),
        )
        if user is not None:
            login(request, user)
            return redirect(next_url or 'dashboard:index')
        return render(request, 'accounts/login.html', {
            'message': 'Invalid username and/or password',
            'next': next_url,
            'username': request.POST.get('username', ''),
        })
    return render(request, 'accounts/login.html', {'next': next_url})


@require_POST
def logout_view(request):
    logout(request)
    return redirect('landing_page:index')


def register_view(request):
    next_url = _next_url(request)
    if request.user.is_authenticated:
        return redirect(next_url or 'dashboard:index')

    form = CustomUserCreationForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        login(request, form.save())
        return redirect(next_url or 'dashboard:index')
    return render(request, 'accounts/register.html', {'form': form, 'next': next_url})
