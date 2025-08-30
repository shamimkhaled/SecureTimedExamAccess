from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.core.exceptions import ValidationError
import uuid

# Create your models here.

class Exam(models.Model):
    """Model representing an exam as per specification"""
    title = models.CharField(max_length=255, help_text="The name of the exam")
    start_time = models.DateTimeField(help_text="The time the exam starts (timezone-aware)")
    end_time = models.DateTimeField(help_text="The time the exam ends (timezone-aware)")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title

    def clean(self):
        """Validate that end_time is after start_time"""
        if self.start_time and self.end_time:
            if self.end_time <= self.start_time:
                raise ValidationError("End time must be after start time")

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    @property
    def duration(self):
        """Return exam duration as timedelta"""
        return self.end_time - self.start_time

    @property
    def is_active(self):
        """Check if exam is currently active"""
        now = timezone.now()
        return self.start_time <= now <= self.end_time

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Exam"
        verbose_name_plural = "Exams"




class ExamAccessToken(models.Model):
    """
    Model representing secure access tokens for exams as per specification
    """
    exam = models.ForeignKey(
        Exam, 
        on_delete=models.CASCADE, 
        related_name='access_tokens',
        help_text="Links the token to a specific exam"
    )
    student = models.ForeignKey(
        User, 
        on_delete=models.CASCADE, 
        related_name='exam_tokens',
        help_text="Links the token to a specific student"
    )
    token = models.CharField(
        max_length=36, 
        unique=True,
        help_text="A cryptographically secure, unique token (e.g., UUID4 or equivalent)"
    )
    is_used = models.BooleanField(
        default=False,
        help_text="Indicates if the token has been consumed"
    )
    valid_from = models.DateTimeField(
        help_text="Start of the token's validity window (timezone-aware)"
    )
    valid_until = models.DateTimeField(
        help_text="End of the token's validity window (timezone-aware)"
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="Timestamp for token creation"
    )
    used_at = models.DateTimeField(
        null=True, 
        blank=True,
        help_text="When this token was consumed"
    )

    def __str__(self):
        return f"{self.exam.title} - {self.student.username} - {self.token[:8]}..."

    def clean(self):
        """Validate token data"""
        if self.valid_from and self.valid_until:
            if self.valid_until <= self.valid_from:
                raise ValidationError("valid_until must be after valid_from")

    def save(self, *args, **kwargs):
        if not self.token:
            # This will be overridden by the service layer with cryptographically secure token
            self.token = str(uuid.uuid4())
        self.clean()
        super().save(*args, **kwargs)

    def is_valid(self):
        """
        Check if token is valid (not used, within time window)
        Business logic as per specification
        """
        now = timezone.now()
        return (
            not self.is_used and
            self.valid_from <= now <= self.valid_until
        )

    def is_expired(self):
        """Check if token is expired"""
        return timezone.now() > self.valid_until

    def is_not_yet_valid(self):
        """Check if token is not yet valid"""
        return timezone.now() < self.valid_from

    @property
    def status(self):
        """Return human-readable token status"""
        if self.is_used:
            return "Used"
        elif self.is_expired():
            return "Expired"
        elif self.is_not_yet_valid():
            return "Not Yet Valid"
        else:
            return "Valid"

    @property
    def time_remaining(self):
        """Return time remaining until expiration"""
        if self.is_used or self.is_expired():
            return None
        return self.valid_until - timezone.now()

    class Meta:
        # Constraints: Ensure uniqueness of the (exam, student) pair as per specification
        unique_together = [['exam', 'student']]
        ordering = ['-created_at']
        verbose_name = "Exam Access Token"
        verbose_name_plural = "Exam Access Tokens"
        
        # Database indexes for performance
        indexes = [
            models.Index(fields=['token'], name='exam_token_idx'),
            models.Index(fields=['valid_until'], name='exam_token_valid_until_idx'),
            models.Index(fields=['is_used'], name='exam_token_is_used_idx'),
            models.Index(fields=['exam', 'student'], name='exam_student_idx'),
        ]