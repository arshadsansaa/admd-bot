import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'wizard_run.settings')

app = Celery('wizard_run')

# Load config from Django settings — all CELERY_* keys
app.config_from_object('django.conf:settings', namespace='CELERY')

# Auto-discover tasks — explicitly include selenium_tasks (not default tasks.py)
app.autodiscover_tasks(related_name='selenium_tasks')
