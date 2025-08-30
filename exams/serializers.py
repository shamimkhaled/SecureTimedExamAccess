from rest_framework import serializers
from django.contrib.auth.models import User
from .models import Exam, ExamAccessToken


class GenerateTokenSerializer(serializers.Serializer):
    """
    Serializer for token generation request payload as per specification:
    {
        "student_id": 42,
        "valid_minutes": 10
    }
    """
    student_id = serializers.IntegerField(
        min_value=1,
        help_text="ID of the student for whom to generate the token"
    )
    valid_minutes = serializers.IntegerField(
        min_value=1, 
        max_value=1440,  # Max 24 hours
        help_text="Token validity duration in minutes"
    )
    regenerate = serializers.BooleanField(
        default=False, 
        required=False,
        help_text="Whether to regenerate if token already exists (bonus feature)"
    )
    
    def validate_student_id(self, value):
        """Validate that student exists - handle edge cases as per specification"""
        if not User.objects.filter(id=value).exists():
            raise serializers.ValidationError("Invalid exam or student")
        return value

    def validate_valid_minutes(self, value):
        """Validate valid_minutes input - handle edge cases as per specification"""
        if value <= 0:
            raise serializers.ValidationError("Invalid input (e.g., negative valid_minutes)")
        if value > 1440:
            raise serializers.ValidationError("Maximum allowed validity is 1440 minutes (24 hours)")
        return value


class TokenResponseSerializer(serializers.Serializer):
    """
    Serializer for token generation success response as per specification:
    {
        "token": "abc123",
        "message": "Token generated successfully"
    }
    """
    token = serializers.CharField(help_text="The generated cryptographically secure token")
    message = serializers.CharField(help_text="Success message")


class ExamSerializer(serializers.ModelSerializer):
    """
    Serializer for exam data in token validation response as per specification
    """
    start_time = serializers.DateTimeField(
        format='%Y-%m-%dT%H:%M:%SZ',
        help_text="Exam start time in ISO format"
    )
    end_time = serializers.DateTimeField(
        format='%Y-%m-%dT%H:%M:%SZ', 
        help_text="Exam end time in ISO format"
    )
    
    class Meta:
        model = Exam
        fields = ['title', 'start_time', 'end_time']


class StudentSerializer(serializers.Serializer):
    """
    Serializer for student data in token validation response as per specification:
    {
        "name": "John Doe", // Concatenation of first_name and last_name
        "email": "john@example.com"
    }
    """
    name = serializers.CharField(help_text="Student name (concatenation of first_name and last_name)")
    email = serializers.EmailField(help_text="Student email address")


class TokenValidationResponseSerializer(serializers.Serializer):
    """
    Serializer for token validation success response as per specification:
    {
        "exam": {
            "title": "Final Python Exam",
            "start_time": "2025-08-25T10:00:00Z",
            "end_time": "2025-08-25T11:30:00Z"
        },
        "student": {
            "name": "John Doe",
            "email": "john@example.com"
        }
    }
    """
    exam = ExamSerializer(help_text="Exam details")
    student = StudentSerializer(help_text="Student details")


class ErrorResponseSerializer(serializers.Serializer):
    """
    Serializer for error responses as per specification:
    - 400 Bad Request: {"detail": "Invalid exam or student"}
    - 403 Forbidden: {"detail": "Unauthorized"}
    - 403 Forbidden: {"detail": "Invalid token"}
    """
    detail = serializers.CharField(help_text="Error message")


# Additional serializers for bonus admin features
class ExamAccessTokenListSerializer(serializers.ModelSerializer):
    """Serializer for listing exam access tokens in admin interface (bonus feature)"""
    exam_title = serializers.CharField(source='exam.title', read_only=True)
    student_name = serializers.SerializerMethodField()
    student_email = serializers.CharField(source='student.email', read_only=True)
    is_expired = serializers.SerializerMethodField()
    is_valid = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    
    class Meta:
        model = ExamAccessToken
        fields = [
            'id', 'token', 'exam_title', 'student_name', 'student_email',
            'is_used', 'is_expired', 'is_valid', 'status',
            'valid_from', 'valid_until', 'created_at', 'used_at'
        ]
        
    def get_student_name(self, obj):
        """Get concatenated student name as per specification"""
        return f"{obj.student.first_name} {obj.student.last_name}".strip() or obj.student.username
    
    def get_is_expired(self, obj):
        """Check if token is expired"""
        return obj.is_expired()
    
    def get_is_valid(self, obj):
        """Check if token is valid"""
        return obj.is_valid()
        
    def get_status(self, obj):
        """Get human-readable status"""
        return obj.status


class ExamDetailSerializer(serializers.ModelSerializer):
    """Detailed exam serializer with token statistics (bonus feature)"""
    token_count = serializers.SerializerMethodField()
    used_token_count = serializers.SerializerMethodField()
    expired_token_count = serializers.SerializerMethodField()
    active_token_count = serializers.SerializerMethodField()
    
    class Meta:
        model = Exam
        fields = [
            'id', 'title', 'start_time', 'end_time', 
            'token_count', 'used_token_count', 'expired_token_count', 'active_token_count',
            'created_at'
        ]
        
    def get_token_count(self, obj):
        """Get total number of tokens for this exam"""
        return obj.access_tokens.count()
    
    def get_used_token_count(self, obj):
        """Get number of used tokens for this exam"""
        return obj.access_tokens.filter(is_used=True).count()
        
    def get_expired_token_count(self, obj):
        """Get number of expired tokens for this exam"""
        from django.utils import timezone
        return obj.access_tokens.filter(valid_until__lt=timezone.now()).count()
        
    def get_active_token_count(self, obj):
        """Get number of active (valid and unused) tokens for this exam"""
        from django.utils import timezone
        now = timezone.now()
        return obj.access_tokens.filter(
            is_used=False,
            valid_from__lte=now,
            valid_until__gt=now
        ).count()


# Validation serializers for different scenarios
class TokenValidationErrorSerializer(serializers.Serializer):
    """Serializer for token validation error responses"""
    detail = serializers.ChoiceField(
        choices=[
            'Invalid token',
            'Token already used', 
            'This access link has expired'
        ]
    )


class TokenGenerationErrorSerializer(serializers.Serializer):
    """Serializer for token generation error responses"""
    detail = serializers.ChoiceField(
        choices=[
            'Invalid exam or student',
            'Token already exists for this student and exam',
            'Unauthorized'
        ]
    )