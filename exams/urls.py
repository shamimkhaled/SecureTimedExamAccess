from django.urls import path
from . import views

app_name = 'exams'

urlpatterns = [
    # Core API endpoints
    path('exams/<int:exam_id>/generate-token/', views.generate_exam_token, name='generate_token'),
    path('exams/access/<str:token>/', views.validate_and_access_exam, name='validate_token'),
    path('exams/<int:exam_id>/tokens/', views.exam_tokens_list, name='exam_tokens_list'),
    path('tokens/<int:token_id>/invalidate/', views.invalidate_token, name='invalidate_token'),
    path('tokens/cleanup-expired/', views.cleanup_expired_tokens, name='cleanup_expired_tokens'),
    
    # Monitoring and documentation endpoints
    path('health/', views.health_check, name='health_check'),
    path('docs/', views.api_documentation, name='api_documentation'),
]