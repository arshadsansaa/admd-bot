import os
from celery import Celery
from celery.schedules import crontab

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'wizard_run.settings')

app = Celery('wizard_run')

# Load config from Django settings — all CELERY_* keys
app.config_from_object('django.conf:settings', namespace='CELERY')

# Auto-discover tasks — explicitly include selenium_tasks (not default tasks.py)
app.autodiscover_tasks(related_name='selenium_tasks')

# =============================================================================
#  BOT SCHEDULE — Change the time here (server timezone = Asia/Kolkata / IST)
# =============================================================================
# This runs ALL saved credentials (BotCredential) at the configured time.
# Format: crontab(hour=HH, minute=MM)   24-hour clock
# Examples:
#     crontab(hour=12, minute=40)   -> daily at 12:40 PM IST
#     crontab(hour=23, minute=30)   -> daily at 11:30 PM IST
#     crontab(minute='*/5')         -> every 5 minutes (testing)
# =============================================================================
BOT_RUN_SCHEDULE = crontab(hour=4, minute=0)   # <-- EDIT THIS LINE

app.conf.beat_schedule = {
    'run-all-saved-credentials': {
        'task': 'accounts.selenium_tasks.task_run_all_credentials',
        'schedule': BOT_RUN_SCHEDULE,
    },
}
