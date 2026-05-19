from django.contrib import admin
from .models import CustomUser, LoginSession, BulkUpload, BotCredential, ScheduledRun


@admin.register(CustomUser)
class CustomUserAdmin(admin.ModelAdmin):
    list_display = ('email', 'full_name', 'is_staff', 'is_active', 'date_joined')
    search_fields = ('email', 'full_name')


@admin.register(BotCredential)
class BotCredentialAdmin(admin.ModelAdmin):
    list_display = ('username', 'office_key', 'created_by', 'created_at')
    search_fields = ('username', 'office_key')


@admin.register(ScheduledRun)
class ScheduledRunAdmin(admin.ModelAdmin):
    list_display = ('id', 'credential', 'scheduled_at', 'status', 'created_by', 'created_at')
    list_filter = ('status',)


@admin.register(LoginSession)
class LoginSessionAdmin(admin.ModelAdmin):
    list_display = ('id', 'username', 'office_key', 'status', 'created_by', 'created_at')
    list_filter = ('status',)
    search_fields = ('username', 'office_key')


@admin.register(BulkUpload)
class BulkUploadAdmin(admin.ModelAdmin):
    list_display = ('id', 'file_name', 'total_rows', 'success_count', 'failed_count', 'created_by', 'created_at')
