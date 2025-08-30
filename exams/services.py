import secrets
import logging
from datetime import timedelta
from django.utils import timezone
from django.contrib.auth.models import User
from django.db import transaction
from typing import Dict, Any, Optional

from .models import Exam, ExamAccessToken

logger = logging.getLogger('exams')


class ExamTokenService:
    """
    Service layer to encapsulate business logic for token generation and validation,
    separate from views and serializers as per specification.
    """
    
    @staticmethod
    def generate_secure_token() -> str:
        """
        Generate a cryptographically secure token using Python's secrets module
        to ensure unpredictability and collision resistance as per specification.
        
        Returns:
            str: A cryptographically secure token (36 characters max)
        """
        # Use secrets.token_urlsafe for cryptographically secure random generation
        # This provides sufficient entropy (~192 bits) for security
        return secrets.token_urlsafe(32)[:36] 
    
    @classmethod
    def generate_exam_token(
        cls, 
        exam_id: int, 
        student_id: int, 
        valid_minutes: int, 
        regenerate: bool = False
    ) -> Dict[str, Any]:
        """
        Generate a secure exam access token for a student.
        Implements all business logic as per specification.
        
        Args:
            exam_id: ID of the exam
            student_id: ID of the student  
            valid_minutes: Token validity duration in minutes
            regenerate: Whether to regenerate if token already exists (bonus feature)
            
        Returns:
            dict: Result containing success status, token data, or error info
        """
        try:
            # Input validation - handle edge cases as per specification
            if valid_minutes <= 0:
                return {
                    'success': False,
                    'error': 'Invalid input (e.g., negative valid_minutes)',
                    'status_code': 400
                }
                
            if valid_minutes > 1440:  # More than 24 hours
                return {
                    'success': False,
                    'error': 'Maximum allowed validity is 1440 minutes (24 hours)',
                    'status_code': 400
                }
            
            # Validate exam exists - handle non-existent exam_id as per specification
            try:
                exam = Exam.objects.get(id=exam_id)
            except Exam.DoesNotExist:
                logger.warning(f"Token generation attempted for non-existent exam {exam_id}")
                return {
                    'success': False,
                    'error': 'Invalid exam or student',
                    'status_code': 400
                }
                
            # Validate student exists - handle non-existent student_id as per specification  
            try:
                student = User.objects.get(id=student_id)
            except User.DoesNotExist:
                logger.warning(f"Token generation attempted for non-existent student {student_id}")
                return {
                    'success': False,
                    'error': 'Invalid exam or student',
                    'status_code': 400
                }
            
            # Ensure token validation is atomic to prevent race conditions as per specification
            with transaction.atomic():
                # Check if token already exists for same student-exam pair
                existing_token = ExamAccessToken.objects.select_for_update().filter(
                    exam=exam, 
                    student=student
                ).first()
                
                # Handle duplicate token case as per specification
                if existing_token and not regenerate:
                    logger.info(f"Duplicate token generation attempted for exam {exam_id}, student {student_id}")
                    return {
                        'success': False,
                        'error': 'Token already exists for this student and exam',
                        'status_code': 400
                    }
                
                # If regenerating, invalidate previous token (bonus feature)
                if existing_token and regenerate:
                    existing_token.is_used = True
                    existing_token.save()
                    logger.info(f"Token regenerated for exam {exam_id}, student {student_id}")
                
                # Generate token with secure algorithm as per specification
                now = timezone.now()
                token_obj = ExamAccessToken.objects.create(
                    exam=exam,
                    student=student,
                    token=cls.generate_secure_token(),
                    valid_from=now,  # Sets valid_from to current time as per specification
                    valid_until=now + timedelta(minutes=valid_minutes)  # Sets valid_until as per specification
                )
                
                logger.info(f"Token generated successfully for exam {exam_id}, student {student_id}")
                
                return {
                    'success': True,
                    'token': token_obj.token,
                    'valid_until': token_obj.valid_until,
                    'status_code': 201  # 201 Created as per specification
                }
                
        except Exception as e:
            logger.error(f"Unexpected error in token generation: {str(e)}")
            return {
                'success': False,
                'error': 'An unexpected error occurred while generating token',
                'status_code': 500
            }
    
    @classmethod
    def validate_and_use_token(cls, token: str) -> Dict[str, Any]:
        """
        Validate token and mark as used if valid.
        Implements all expected checks as per specification:
        - Token exists in ExamAccessToken
        - Current time is within valid_from and valid_until  
        - is_used is False
        - Upon successful validation, mark token as is_used=True
        
        Args:
            token: The token string to validate
            
        Returns:
            dict: Validation result with exam and student data or error info
        """
        if not token or not token.strip():
            return {
                'success': False,
                'error': 'Token is required',
                'status_code': 400
            }
            
        try:
            # Ensure concurrent access attempts are handled atomically as per specification
            with transaction.atomic():
                # Get token object with select_for_update to prevent race conditions
                token_obj = ExamAccessToken.objects.select_for_update().select_related(
                    'exam', 'student'
                ).filter(token=token.strip()).first()
                
                # Check: Token exists in ExamAccessToken
                if not token_obj:
                    logger.warning(f"Token validation failed - invalid token: {token[:8]}...")
                    return {
                        'success': False,
                        'error': 'Invalid token',
                        'status_code': 403 
                    }
                
                # Check: is_used is False
                if token_obj.is_used:
                    logger.warning(f"Token validation failed - already used: {token[:8]}...")
                    return {
                        'success': False,
                        'error': 'Token already used',
                        'status_code': 403  
                    }
                
                now = timezone.now()
                
                # Check: Current time is within valid_from and valid_until
                if now > token_obj.valid_until:
                    logger.warning(f"Token validation failed - expired: {token[:8]}...")
                    return {
                        'success': False,
                        'error': 'This access link has expired',
                        'status_code': 403  
                    }
                
                if now < token_obj.valid_from:
                    logger.warning(f"Token validation failed - not yet valid: {token[:8]}...")
                    return {
                        'success': False,
                        'error': 'This access link is not yet valid',
                        'status_code': 403
                    }
                
                # Upon successful validation, mark token as is_used=True as per specification
                token_obj.is_used = True
                token_obj.used_at = now
                token_obj.save()
                
                logger.info(f"Token validated successfully: {token[:8]}... for exam {token_obj.exam.id}")
                
                # Return exam and student data as per specification format
                return {
                    'success': True,
                    'exam': {
                        'title': token_obj.exam.title,
                        'start_time': token_obj.exam.start_time.isoformat(),
                        'end_time': token_obj.exam.end_time.isoformat(),
                    },
                    'student': {
                        # Concatenation of first_name and last_name as per specification
                        'name': f"{token_obj.student.first_name} {token_obj.student.last_name}".strip() or token_obj.student.username,
                        'email': token_obj.student.email,
                    },
                    'status_code': 200 
                }
                
        except Exception as e:
            logger.error(f"Unexpected error in token validation: {str(e)}")
            return {
                'success': False,
                'error': 'An unexpected error occurred while validating token',
                'status_code': 500
            }
    
    @classmethod
    def cleanup_expired_tokens(cls, days_old: int = 0) -> int:
        """
        Remove expired tokens from database (bonus feature).
        Create a management command to clean up expired tokens as per specification.
        
        Args:
            days_old: Only delete tokens expired more than this many days ago.
                     Default 0 means delete all expired tokens.
            
        Returns:
            int: Number of tokens deleted
        """
        try:
            cutoff_date = timezone.now()
            if days_old > 0:
                cutoff_date = cutoff_date - timedelta(days=days_old)
            
            deleted_info = ExamAccessToken.objects.filter(
                valid_until__lt=cutoff_date
            ).delete()
            
            deleted_count = deleted_info[0]
            logger.info(f"Cleaned up {deleted_count} expired tokens")
            return deleted_count
            
        except Exception as e:
            logger.error(f"Error cleaning up expired tokens: {str(e)}")
            return 0
    
    @classmethod
    def invalidate_token_on_failed_attempt(cls, token: str) -> bool:
        """
        Invalidate tokens on failed attempts due to incorrect token values 
        (bonus feature as per specification).
        
        Args:
            token: The invalid token to mark as used
            
        Returns:
            bool: True if token was found and invalidated, False otherwise
        """
        try:
            token_obj = ExamAccessToken.objects.filter(token=token).first()
            if token_obj and not token_obj.is_used and not token_obj.is_expired():
                token_obj.is_used = True
                token_obj.used_at = timezone.now()
                token_obj.save()
                logger.info(f"Token {token[:8]}... invalidated due to failed attempt")
                return True
            return False
        except Exception as e:
            logger.error(f"Error invalidating token on failed attempt: {str(e)}")
            return False
        
        
        