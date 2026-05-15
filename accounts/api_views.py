from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from django.db.models import Q, Count
from .models import LoginSession, BulkUpload


class ActivityPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 200


class ActivityLogAPI(APIView):
    """
    GET /api/wizard_run_bot_activity/

    All login session activity with filters and pagination.

    Query Params:
        - username        : Filter by username (partial match)
        - office_key      : Filter by office key (partial match)
        - status          : Filter by status (PENDING, RUNNING, SUCCESS, FAILED)
        - upload_id       : Filter by bulk upload ID
        - uploaded_by     : Filter by uploader email
        - date_from       : Filter from date (YYYY-MM-DD)
        - date_to         : Filter to date (YYYY-MM-DD)
        - search          : Search across username, office_key, error_message, filename
        - ordering        : Order by field (e.g. -created_at, username, status)
        - page            : Page number
        - page_size       : Items per page (max 200)
    """

    def get(self, request):
        queryset = LoginSession.objects.select_related('bulk_upload', 'created_by').all()

        # --- FILTERS ---
        username = request.query_params.get('username')
        if username:
            queryset = queryset.filter(username__icontains=username)

        office_key = request.query_params.get('office_key')
        if office_key:
            queryset = queryset.filter(office_key__icontains=office_key)

        task_status = request.query_params.get('status')
        if task_status:
            queryset = queryset.filter(status__iexact=task_status)

        upload_id = request.query_params.get('upload_id')
        if upload_id:
            queryset = queryset.filter(bulk_upload_id=upload_id)

        uploaded_by = request.query_params.get('uploaded_by')
        if uploaded_by:
            queryset = queryset.filter(created_by__email__icontains=uploaded_by)

        date_from = request.query_params.get('date_from')
        if date_from:
            queryset = queryset.filter(created_at__date__gte=date_from)

        date_to = request.query_params.get('date_to')
        if date_to:
            queryset = queryset.filter(created_at__date__lte=date_to)

        # --- SEARCH (across multiple fields) ---
        search = request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                Q(username__icontains=search) |
                Q(office_key__icontains=search) |
                Q(error_message__icontains=search) |
                Q(bulk_upload__file_name__icontains=search)
            )

        # --- ORDERING ---
        ordering = request.query_params.get('ordering', '-created_at')
        allowed_orderings = [
            'created_at', '-created_at',
            'username', '-username',
            'status', '-status',
            'office_key', '-office_key',
        ]
        if ordering in allowed_orderings:
            queryset = queryset.order_by(ordering)
        else:
            queryset = queryset.order_by('-created_at')

        # --- PAGINATION ---
        paginator = ActivityPagination()
        page = paginator.paginate_queryset(queryset, request)

        data = []
        for session in page:
            data.append({
                'id': session.id,
                'username': session.username,
                'office_key': session.office_key,
                'status': session.status,
                'error_message': session.error_message,
                'created_at': session.created_at.strftime('%Y-%m-%d %H:%M:%S') if session.created_at else None,
                'updated_at': session.updated_at.strftime('%Y-%m-%d %H:%M:%S') if session.updated_at else None,
                'logged_in_user': {
                    'email': session.created_by.email if session.created_by else None,
                    'full_name': session.created_by.full_name if session.created_by else None,
                } if session.created_by else None,
                'bulk_upload': {
                    'id': session.bulk_upload.id,
                    'file_name': session.bulk_upload.file_name,
                    'total_rows': session.bulk_upload.total_rows,
                    'success_count': session.bulk_upload.success_count,
                    'failed_count': session.bulk_upload.failed_count,
                    'skipped_count': session.bulk_upload.skipped_count,
                    'created_at': session.bulk_upload.created_at.strftime('%Y-%m-%d %H:%M:%S') if session.bulk_upload.created_at else None,
                    'uploaded_by': session.bulk_upload.created_by.email if session.bulk_upload.created_by else None,
                } if session.bulk_upload else None,
            })

        return paginator.get_paginated_response(data)


class ActivityStatsAPI(APIView):
    """
    GET /api/wizard_run_bot_activity/stats/

    Summary stats for dashboard.
    """

    def get(self, request):
        sessions = LoginSession.objects.all()
        stats = {
            'total_sessions': sessions.count(),
            'success': sessions.filter(status='SUCCESS').count(),
            'failed': sessions.filter(status='FAILED').count(),
            'pending': sessions.filter(status='PENDING').count(),
            'running': sessions.filter(status='RUNNING').count(),
            'total_uploads': BulkUpload.objects.count(),
        }
        return Response(stats)
