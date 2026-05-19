from django.urls import path
from . import views

urlpatterns = [
    path('', views.signin_view, name='signin'),
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('credentials/add/', views.add_credential_view, name='add_credential'),
    path('credentials/<int:pk>/delete/', views.delete_credential_view, name='delete_credential'),
    path('credentials/<int:pk>/toggle/', views.toggle_credential_view, name='toggle_credential'),
    path('sessions/<int:pk>/cancel/', views.cancel_session_view, name='cancel_session'),
    path('sessions/download/', views.download_sessions_view, name='download_sessions'),
    path('bulk-uploads/', views.bulk_upload_list_view, name='bulk_upload_list'),
    path('bulk-uploads/upload/', views.bulk_upload_view, name='bulk_upload'),
    path('bulk-uploads/sample-csv/', views.sample_csv_view, name='sample_csv'),
    path('bulk-uploads/<int:pk>/download/', views.download_upload_view, name='download_upload'),
    path('bulk-uploads/<int:pk>/', views.bulk_upload_detail_view, name='bulk_upload_detail'),
    path('logout/', views.logout_view, name='logout'),
]

