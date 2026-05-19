from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.conf import settings


class CustomUserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('Email is required')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        return self.create_user(email, password, **extra_fields)


class CustomUser(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=150, blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(auto_now_add=True)

    objects = CustomUserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    def __str__(self):
        return self.email


class LoginSession(models.Model):
    STATUS_PENDING = 'PENDING'
    STATUS_RUNNING = 'RUNNING'
    STATUS_SUCCESS = 'SUCCESS'
    STATUS_FAILED = 'FAILED'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_RUNNING, 'Running'),
        (STATUS_SUCCESS, 'Success'),
        (STATUS_FAILED, 'Failed'),
    ]

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='login_sessions'
    )
    bulk_upload = models.ForeignKey(
        'BulkUpload',
        on_delete=models.CASCADE,
        related_name='sessions',
        null=True,
        blank=True,
    )
    username = models.CharField(max_length=255)
    password = models.CharField(max_length=255)
    office_key = models.CharField(max_length=100)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    error_message = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.username} | {self.office_key} | {self.status}"


class BulkUpload(models.Model):
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='bulk_uploads'
    )
    file_name = models.CharField(max_length=255)
    csv_file = models.FileField(upload_to='bulk_uploads/', blank=True, null=True)
    total_rows = models.PositiveIntegerField(default=0)
    success_count = models.PositiveIntegerField(default=0)
    failed_count = models.PositiveIntegerField(default=0)
    skipped_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.file_name} ({self.total_rows} rows)"

    @property
    def running_count(self):
        return self.sessions.filter(status=LoginSession.STATUS_RUNNING).count()

    @property
    def pending_count(self):
        return self.sessions.filter(status=LoginSession.STATUS_PENDING).count()


class BotCredential(models.Model):
    """Stored AdvancedMD credential — user can save multiple and pick one when scheduling."""
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='bot_credentials',
    )
    username = models.CharField(max_length=255)
    password = models.CharField(max_length=255)
    office_key = models.CharField(max_length=100)
    is_active = models.BooleanField(
        default=True,
        help_text='If checked, this credential will be picked by the scheduled bot run.'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['username']
        unique_together = ('created_by', 'username', 'office_key')

    def __str__(self):
        return f"{self.username} / {self.office_key}"


class ScheduledRun(models.Model):
    """A bot run scheduled to fire at a specific datetime using one saved credential."""
    STATUS_PENDING = 'PENDING'
    STATUS_TRIGGERED = 'TRIGGERED'
    STATUS_CANCELLED = 'CANCELLED'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_TRIGGERED, 'Triggered'),
        (STATUS_CANCELLED, 'Cancelled'),
    ]

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='scheduled_runs',
    )
    credential = models.ForeignKey(
        BotCredential,
        on_delete=models.CASCADE,
        related_name='scheduled_runs',
    )
    scheduled_at = models.DateTimeField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    login_session = models.ForeignKey(
        LoginSession,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='scheduled_runs',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-scheduled_at']

    def __str__(self):
        return f"{self.credential.username} @ {self.scheduled_at:%Y-%m-%d %H:%M} [{self.status}]"

