from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from django.shortcuts import get_object_or_404
from django.views.decorators.cache import never_cache
from django.utils import timezone
import logging
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from .models import Exam, ExamAccessToken
from .services import ExamTokenService
from .serializers import (
    GenerateTokenSerializer,
    TokenResponseSerializer,
    TokenValidationResponseSerializer,
    ErrorResponseSerializer
)

logger = logging.getLogger('exams')

@swagger_auto_schema(
    method='post',
    operation_description="Generate a secure, time-bound, one-time-use access token for a student to access an exam. Only instructors (is_staff=True) can access this endpoint.",
    request_body=GenerateTokenSerializer,
    responses={
        201: openapi.Response('Token generated successfully', TokenResponseSerializer),
        400: openapi.Response('Invalid input data', ErrorResponseSerializer),
        403: openapi.Response('Unauthorized', ErrorResponseSerializer),
        404: openapi.Response('Exam not found', ErrorResponseSerializer),
    },
    manual_parameters=[
        openapi.Parameter('exam_id', openapi.IN_PATH, description="ID of the exam", type=openapi.TYPE_INTEGER),
    ]
)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def generate_exam_token(request, exam_id):
    if not request.user.is_staff:
        logger.warning(f"Unauthorized token generation attempt by user {request.user.id}")
        return Response(
            {"detail": "Unauthorized"},
            status=status.HTTP_403_FORBIDDEN
        )
    exam = get_object_or_404(Exam, id=exam_id)
    serializer = GenerateTokenSerializer(data=request.data)
    if not serializer.is_valid():
        errors = serializer.errors
        if 'student_id' in errors:
            error_msg = errors['student_id'][0] if errors['student_id'] else "Invalid exam or student"
        elif 'valid_minutes' in errors:
            error_msg = errors['valid_minutes'][0] if errors['valid_minutes'] else "Invalid input"
        else:
            error_msg = "Invalid input data"
        return Response(
            {"detail": error_msg},
            status=status.HTTP_400_BAD_REQUEST
        )
    validated_data = serializer.validated_data
    result = ExamTokenService.generate_exam_token(
        exam_id=exam_id,
        student_id=validated_data['student_id'],
        valid_minutes=validated_data['valid_minutes'],
        regenerate=validated_data.get('regenerate', False)
    )
    if result['success']:
        logger.info(f"Token generated for exam {exam_id}, student {validated_data['student_id']} by instructor {request.user.id}")
        return Response(
            {
                "token": result['token'],
                "message": "Token generated successfully"
            },
            status=status.HTTP_201_CREATED
        )
    else:
        logger.warning(f"Token generation failed for exam {exam_id}, student {validated_data['student_id']}: {result['error']}")
        return Response(
            {"detail": result['error']},
            status=result['status_code']
   
   
        )

class TokenValidationThrottle(AnonRateThrottle):
    """Custom throttle for token validation endpoint to prevent brute-force attacks as per specification"""
    rate = '100/hour'




@api_view(['GET'])
@permission_classes([AllowAny])
@throttle_classes([TokenValidationThrottle])
@never_cache
def validate_and_access_exam(request, **kwargs):
    token = kwargs.get('token')
    if not token:
        return Response(
            {"detail": "Token is required"},
            status=status.HTTP_400_BAD_REQUEST
        )
    result = ExamTokenService.validate_and_use_token(token)
    if result['success']:
        logger.info(f"Token {token[:8]}... validated successfully")
        return Response(
            {
                "exam": result['exam'],
                "student": result['student']
            },
            status=status.HTTP_200_OK
        )
    else:
        logger.warning(f"Token validation failed for {token[:8]}...: {result['error']}")
        if result['error'] == 'Invalid token':
            ExamTokenService.invalidate_token_on_failed_attempt(token)
        return Response(
            {"detail": result['error']},
            status=result['status_code']
        )
        
        
        


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def exam_tokens_list(request, exam_id):
    if not request.user.is_staff:
        return Response(
            {"detail": "Unauthorized"},
            status=status.HTTP_403_FORBIDDEN
        )
    exam = get_object_or_404(Exam, id=exam_id)
    tokens = exam.access_tokens.select_related('student').all()
    token_data = []
    for token in tokens:
        token_data.append({
            'id': token.id,
            'token': f"{token.token[:8]}...",
            'student_name': f"{token.student.first_name} {token.student.last_name}".strip() or token.student.username,
            'student_email': token.student.email,
            'is_used': token.is_used,
            'is_expired': token.is_expired(),
            'is_valid': token.is_valid(),
            'status': token.status,
            'valid_from': token.valid_from,
            'valid_until': token.valid_until,
            'created_at': token.created_at,
            'used_at': token.used_at,
        })
    return Response({
        'exam': {
            'id': exam.id,
            'title': exam.title,
            'start_time': exam.start_time,
            'end_time': exam.end_time,
        },
        'tokens': token_data,
        'statistics': {
            'total_count': len(token_data),
            'used_count': sum(1 for t in token_data if t['is_used']),
            'expired_count': sum(1 for t in token_data if t['is_expired']),
            'active_count': sum(1 for t in token_data if t['is_valid']),
        }
    })
    
    
    

@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def invalidate_token(request, token_id):
    if not request.user.is_staff:
        return Response(
            {"detail": "Unauthorized"},
            status=status.HTTP_403_FORBIDDEN
        )
    token = get_object_or_404(ExamAccessToken, id=token_id)
    if token.is_used:
        return Response(
            {"detail": "Token is already used"},
            status=status.HTTP_400_BAD_REQUEST
        )
    token.is_used = True
    token.used_at = timezone.now()
    token.save()
    logger.info(f"Token {token.token[:8]}... invalidated by instructor {request.user.id}")
    return Response(
        {"message": "Token invalidated successfully"},
        status=status.HTTP_200_OK
    )



@swagger_auto_schema(
    method='post',
    operation_description="Clean up expired tokens. Only instructors (is_staff=True) can access this endpoint.",
    request_body=openapi.Schema(
        type=openapi.TYPE_OBJECT,
        properties={
            'days': openapi.Schema(type=openapi.TYPE_INTEGER, description="Number of days to consider tokens expired", default=0),
        }
    ),
    responses={
        200: openapi.Response('Tokens cleaned up successfully', openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                'message': openapi.Schema(type=openapi.TYPE_STRING),
                'deleted_count': openapi.Schema(type=openapi.TYPE_INTEGER),
                'criteria': openapi.Schema(type=openapi.TYPE_STRING),
            }
        )),
        403: openapi.Response('Unauthorized', ErrorResponseSerializer),
    }
)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def cleanup_expired_tokens(request):
    if not request.user.is_staff:
        return Response(
            {"detail": "Unauthorized"},
            status=status.HTTP_403_FORBIDDEN
        )
    days = request.data.get('days', 0)
    try:
        days = int(days)
    except (ValueError, TypeError):
        days = 0
    deleted_count = ExamTokenService.cleanup_expired_tokens(days_old=days)
    logger.info(f"Cleaned up {deleted_count} expired tokens by instructor {request.user.id}")
    return Response(
        {
            "message": f"Cleaned up {deleted_count} expired tokens",
            "deleted_count": deleted_count,
            "criteria": f"Tokens expired more than {days} days ago" if days > 0 else "All expired tokens"
        },
        status=status.HTTP_200_OK
    )



@api_view(['GET'])
@permission_classes([AllowAny])
def health_check(request):
    return Response({
        'status': 'healthy',
        'service': 'Secure Exam Access API',
        'version': '1.0.0'
    })




@api_view(['GET'])
@permission_classes([AllowAny])
def api_documentation(request):
    return Response({
        'title': 'Secure Exam Access Link API',
        'description': 'API for generating and validating secure, time-bound, one-time-use access links to online exams',
        'version': '1.0.0',
        'endpoints': {
            'generate_token': {
                'method': 'POST',
                'url': '/api/exams/<exam_id>/generate-token/',
                'authentication': 'Instructor only (is_staff=True)',
                'description': 'Generate secure exam access token for a student'
            },
            'validate_token': {
                'method': 'GET',
                'url': '/api/exams/access/<token>/',
                'authentication': 'Public (no login required)',
                'description': 'Validate token and provide exam access'
            },
            'cleanup_expired': {
                'method': 'POST',
                'url': '/api/tokens/cleanup-expired/',
                'authentication': 'Instructor only',
                'description': 'Clean up expired tokens (bonus feature)'
            }
        },
        'security_features': [
            'Cryptographically secure tokens using Python secrets module',
            'Single-use token enforcement',
            'Time-bound access control',
            'Rate limiting on public endpoints',
            'Comprehensive logging and monitoring'
        ]
    })