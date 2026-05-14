from django.urls import path
from . import views

urlpatterns = [
    path('', views.signin_view, name='signin'),
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('run-login/', views.run_login_view, name='run_login'),
    path('bulk-uploads/', views.bulk_upload_list_view, name='bulk_upload_list'),
    path('bulk-uploads/upload/', views.bulk_upload_view, name='bulk_upload'),
    path('bulk-uploads/sample-csv/', views.sample_csv_view, name='sample_csv'),
    path('bulk-uploads/<int:pk>/download/', views.download_upload_view, name='download_upload'),
    path('bulk-uploads/<int:pk>/', views.bulk_upload_detail_view, name='bulk_upload_detail'),
    path('logout/', views.logout_view, name='logout'),
]

