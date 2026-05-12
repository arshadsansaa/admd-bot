from django.shortcuts import render, redirect
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.views.decorators.http import require_POST
from .forms import SignInForm, AdvancedMDCredentialForm
from .models import LoginSession


def signin_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    form = SignInForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.get_user()
        login(request, user)
        return redirect('dashboard')

    return render(request, 'accounts/signin.html', {'form': form})


@login_required
def dashboard_view(request):
    cred_form = AdvancedMDCredentialForm()
    sessions_qs = LoginSession.objects.filter(created_by=request.user)
    paginator = Paginator(sessions_qs, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'accounts/dashboard.html', {
        'user': request.user,
        'cred_form': cred_form,
        'page_obj': page_obj,
    })


@login_required
@require_POST
def run_login_view(request):
    form = AdvancedMDCredentialForm(request.POST)
    if not form.is_valid():
        sessions_qs = LoginSession.objects.filter(created_by=request.user)
        paginator = Paginator(sessions_qs, 10)
        page_obj = paginator.get_page(request.GET.get('page'))
        return render(request, 'accounts/dashboard.html', {
            'user': request.user,
            'cred_form': form,
            'page_obj': page_obj,
        })

    session = LoginSession.objects.create(
        created_by=request.user,
        username=form.cleaned_data['username'],
        password=form.cleaned_data['password'],
        office_key=form.cleaned_data['office_key'],
        status=LoginSession.STATUS_RUNNING,
    )

    from .selenium_tasks import task_run_eod_wizard
    task_run_eod_wizard.delay(session.pk)

    return redirect('dashboard')


def logout_view(request):
    logout(request)
    return redirect('signin')


