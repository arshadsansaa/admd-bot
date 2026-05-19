import csv
import io

import chardet
from django.http import HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.views.decorators.http import require_POST
from .forms import SignInForm, BotCredentialForm
from .models import LoginSession, BulkUpload, BotCredential


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
    bot_cred_form = BotCredentialForm()

    sessions_qs = LoginSession.objects.filter(created_by=request.user)
    paginator = Paginator(sessions_qs, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    credentials = BotCredential.objects.filter(created_by=request.user)

    # Pretty label for the configured BOT_RUN_SCHEDULE (set in wizard_run/celery.py)
    bot_schedule_label = 'the configured time'
    try:
        from wizard_run.celery import BOT_RUN_SCHEDULE
        hours = sorted(BOT_RUN_SCHEDULE.hour) if BOT_RUN_SCHEDULE.hour else []
        minutes = sorted(BOT_RUN_SCHEDULE.minute) if BOT_RUN_SCHEDULE.minute else []
        if len(hours) == 1 and len(minutes) == 1:
            h, m = hours[0], minutes[0]
            suffix = 'AM' if h < 12 else 'PM'
            h12 = h % 12 or 12
            bot_schedule_label = f'{h12}:{m:02d} {suffix}'
    except Exception:
        pass

    return render(request, 'accounts/dashboard.html', {
        'user': request.user,
        'bot_cred_form': bot_cred_form,
        'credentials': credentials,
        'page_obj': page_obj,
        'bot_schedule_label': bot_schedule_label,
    })


@login_required
@require_POST
def add_credential_view(request):
    form = BotCredentialForm(request.POST)
    if form.is_valid():
        cred = form.save(commit=False)
        cred.created_by = request.user
        try:
            cred.save()
            messages.success(request, f'Credential "{cred.username}" saved.')
        except Exception as e:
            messages.error(request, f'Could not save credential: {e}')
    else:
        messages.error(request, 'Please fill all credential fields correctly.')
    return redirect('dashboard')


@login_required
@require_POST
def delete_credential_view(request, pk):
    cred = get_object_or_404(BotCredential, pk=pk, created_by=request.user)
    name = cred.username
    cred.delete()
    messages.success(request, f'Credential "{name}" deleted.')
    return redirect('dashboard')


@login_required
@require_POST
def toggle_credential_view(request, pk):
    cred = get_object_or_404(BotCredential, pk=pk, created_by=request.user)
    cred.is_active = not cred.is_active
    cred.save(update_fields=['is_active'])
    state = 'enabled' if cred.is_active else 'disabled'
    messages.success(request, f'"{cred.username}" {state} for auto-run.')
    return redirect('dashboard')


@login_required
@require_POST
def bulk_upload_view(request):
    csv_file = request.FILES.get('csv_file')
    if not csv_file:
        messages.error(request, 'Please select a CSV file.')
        return redirect('bulk_upload_list')

    if not csv_file.name.lower().endswith('.csv'):
        messages.error(request, 'Only .csv files are allowed.')
        return redirect('bulk_upload_list')

    # Read raw bytes and detect encoding (handles any encoding, not just UTF-8)
    raw_data = csv_file.read()
    detected = chardet.detect(raw_data)
    encoding = detected.get('encoding') or 'utf-8'

    try:
        text = raw_data.decode(encoding)
    except (UnicodeDecodeError, LookupError):
        for fallback_enc in ('utf-8-sig', 'latin-1', 'cp1252', 'iso-8859-1'):
            try:
                text = raw_data.decode(fallback_enc)
                break
            except (UnicodeDecodeError, LookupError):
                continue
        else:
            messages.error(request, 'Could not decode the CSV file. Please check the file encoding.')
            return redirect('bulk_upload_list')

    # Strip BOM if present
    text = text.lstrip('\ufeff')

    reader = csv.DictReader(io.StringIO(text))

    # Normalize header names (strip whitespace, lowercase)
    if reader.fieldnames:
        reader.fieldnames = [f.strip().lower() for f in reader.fieldnames]

    required_cols = {'username', 'password', 'office_key'}
    if not reader.fieldnames or not required_cols.issubset(set(reader.fieldnames)):
        messages.error(
            request,
            f'CSV must have columns: username, password, office_key. '
            f'Found: {", ".join(reader.fieldnames) if reader.fieldnames else "none"}'
        )
        return redirect('bulk_upload_list')

    from .selenium_tasks import task_run_eod_wizard

    # Create BulkUpload record (save original file for reference download)
    csv_file.seek(0)
    bulk = BulkUpload.objects.create(
        created_by=request.user,
        file_name=csv_file.name,
        csv_file=csv_file,
    )

    created_count = 0
    skipped_count = 0
    for row_num, row in enumerate(reader, start=2):
        username = (row.get('username') or '').strip()
        password = (row.get('password') or '').strip()
        office_key = (row.get('office_key') or '').strip()

        if not username or not password or not office_key:
            skipped_count += 1
            continue

        session = LoginSession.objects.create(
            created_by=request.user,
            bulk_upload=bulk,
            username=username,
            password=password,
            office_key=office_key,
            status=LoginSession.STATUS_RUNNING,
        )
        task_run_eod_wizard.delay(session.pk)
        created_count += 1

    bulk.total_rows = created_count + skipped_count
    bulk.skipped_count = skipped_count
    bulk.save()

    if created_count:
        messages.success(request, f'Uploaded "{csv_file.name}" — {created_count} session(s) queued.')
    if skipped_count:
        messages.warning(request, f'{skipped_count} row(s) skipped due to missing data.')
    if not created_count and not skipped_count:
        messages.warning(request, 'CSV file was empty or had no valid rows.')

    return redirect('bulk_upload_detail', pk=bulk.pk)


@login_required
def bulk_upload_list_view(request):
    uploads_qs = BulkUpload.objects.filter(created_by=request.user)
    paginator = Paginator(uploads_qs, 10)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'accounts/bulk_upload_list.html', {
        'user': request.user,
        'page_obj': page_obj,
    })


@login_required
def bulk_upload_detail_view(request, pk):
    bulk = get_object_or_404(BulkUpload, pk=pk, created_by=request.user)

    # Update live counts
    bulk.success_count = bulk.sessions.filter(status=LoginSession.STATUS_SUCCESS).count()
    bulk.failed_count = bulk.sessions.filter(status=LoginSession.STATUS_FAILED).count()
    bulk.save(update_fields=['success_count', 'failed_count'])

    sessions_qs = bulk.sessions.all()
    paginator = Paginator(sessions_qs, 20)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'accounts/bulk_upload_detail.html', {
        'user': request.user,
        'bulk': bulk,
        'page_obj': page_obj,
    })

    return redirect('dashboard')


@login_required
def download_upload_view(request, pk):
    bulk = get_object_or_404(BulkUpload, pk=pk, created_by=request.user)
    if not bulk.csv_file:
        messages.error(request, 'Original file is not available for this upload.')
        return redirect('bulk_upload_detail', pk=pk)
    response = HttpResponse(bulk.csv_file.read(), content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{bulk.file_name}"'
    return response


@login_required
def sample_csv_view(request):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="sample_bulk_upload.csv"'
    writer = csv.writer(response)
    writer.writerow(['username', 'password', 'office_key'])
    writer.writerow(['TECH01', 'mypassword', '153418'])
    writer.writerow(['TECH02', 'anotherpass', '153419'])
    return response


def logout_view(request):
    logout(request)
    return redirect('signin')


@login_required
@require_POST
def cancel_session_view(request, pk):
    """Mark a PENDING/RUNNING LoginSession as FAILED ('Cancelled by user').
    Note: this does not kill an already-running Selenium browser; it only stops
    new pickup and marks the session for the UI."""
    session = get_object_or_404(LoginSession, pk=pk, created_by=request.user)
    if session.status in (LoginSession.STATUS_PENDING, LoginSession.STATUS_RUNNING):
        session.status = LoginSession.STATUS_FAILED
        session.error_message = 'Cancelled by user.'
        session.save(update_fields=['status', 'error_message', 'updated_at'])
        messages.success(request, f'Session #{session.pk} cancelled.')
    else:
        messages.warning(request, 'Only pending/running sessions can be cancelled.')
    return redirect('dashboard')


@login_required
def download_sessions_view(request):
    """Download all login sessions of the current user as CSV."""
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="login_sessions.csv"'
    writer = csv.writer(response)
    writer.writerow(['id', 'username', 'office_key', 'status', 'error_message', 'created_at', 'updated_at'])
    for s in LoginSession.objects.filter(created_by=request.user):
        writer.writerow([
            s.pk, s.username, s.office_key, s.status,
            s.error_message,
            s.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            s.updated_at.strftime('%Y-%m-%d %H:%M:%S'),
        ])
    return response


