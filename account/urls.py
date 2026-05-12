from django.urls import path
from . import views

urlpatterns = [
    path('', views.signin_view, name='signin'),
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('run-login/', views.run_login_view, name='run_login'),
    path('logout/', views.logout_view, name='logout'),
]

