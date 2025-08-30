from django.contrib import admin
from django.utils.html import format_html
from django.utils import timezone
from django.urls import reverse
from django.http import HttpResponseRedirect
from .models import Exam, ExamAccessToken


@admin.register(Exam)
class ExamAdmin(admin.ModelAdmin):
    """Django admin interface for Exam model - bonus feature as per specification"""
    
    list_display = ['title', 'start_time', 'end_time', 'token_count', 'used_tokens', 'created_at']
    list_filter = [
        'start_time', 
        'end_time', 
        'created_at',
        ('start_time', admin.DateFieldListFilter),
        ('end_time', admin.DateFieldListFilter),
    ]
    search_fields = ['title']
    readonly_fields = ['created_at', 'updated_at', 'token_statistics']
    date_hierarchy = 'start_time'
    
    fieldsets = (
        ('Exam Information', {
            'fields': ('title',)
        }),
        ('Schedule', {
            'fields': ('start_time', 'end_time'),
            'description': 'Exam timing (timezone-aware as per specification)'
        }),
        ('Statistics', {
            'fields': ('token_statistics',),
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def token_count(self, obj):
        """Display total number of tokens for this exam"""
        count = obj.access_tokens.count()
        if count > 0:
            # Create link to filtered token list
            url = reverse('admin:exams_examaccesstoken_changelist')
            return format_html(
                '<a href="{}?exam__id={}">{} tokens</a>',
                url, obj.id, count
            )
        return "0 tokens"
    token_count.short_description = 'Access Tokens'
    
    def used_tokens(self, obj):
        """Display number of used tokens"""
        used = obj.access_tokens.filter(is_used=True).count()
        total = obj.access_tokens.count()
        if total > 0:
            percentage = round((used / total) * 100, 1)
            return f"{used}/{total} ({percentage}%)"
        return "0/0"
    used_tokens.short_description = 'Used Tokens'
    
    def token_statistics(self, obj):
        """Display detailed token statistics"""
        tokens = obj.access_tokens.all()
        total = tokens.count()
        if total == 0:
            return "No tokens generated yet"
        
        used = tokens.filter(is_used=True).count()
        expired = tokens.filter(valid_until__lt=timezone.now()).count()
        active = tokens.filter(
            is_used=False,
            valid_from__lte=timezone.now(),
            valid_until__gt=timezone.now()
        ).count()
        
        stats = [
            f"Total: {total}",
            f"Used: {used}",
            f"Expired: {expired}", 
            f"Active: {active}",
        ]
        
        return format_html("<br>".join(stats))
    token_statistics.short_description = 'Token Statistics'


@admin.register(ExamAccessToken)
class ExamAccessTokenAdmin(admin.ModelAdmin):
    """
    Django admin interface for ExamAccessToken with filters as per specification:
    - Add Django admin panel support for ExamAccessToken with filters for is_used, valid_until, and exam
    """
    
    list_display = [
        'masked_token', 
        'exam_link', 
        'student_name', 
        'student_email', 
        'status_display', 
        'valid_until', 
        'created_at'
    ]
    
    # Filters as specified in requirements: is_used, valid_until, and exam
    list_filter = [
        'is_used',
        'exam', 
        ('valid_until', admin.DateFieldListFilter),
        ('created_at', admin.DateFieldListFilter),
        'exam__title',
    ]
    
    search_fields = [
        'exam__title', 
        'student__username', 
        'student__email', 
        'student__first_name', 
        'student__last_name',
        'token'
    ]
    
    readonly_fields = [
        'token', 
        'created_at', 
        'used_at', 
        'status_display', 
        'time_remaining_display',
        'validation_url'
    ]
    
    raw_id_fields = ['exam', 'student']
    
    fieldsets = (
        ('Token Information', {
            'fields': ('token', 'status_display', 'validation_url'),
            'description': 'Cryptographically secure token information'
        }),
        ('Usage Status', {
            'fields': ('is_used', 'used_at'),
        }),
        ('Associated Records', {
            'fields': ('exam', 'student'),
        }),
        ('Validity Window', {
            'fields': ('valid_from', 'valid_until', 'time_remaining_display'),
            'description': 'Time-bound access control as per specification'
        }),
        ('Metadata', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        }),
    )
    
    def masked_token(self, obj):
        """Display masked token for security - avoid exposing full tokens in admin"""
        if len(obj.token) > 8:
            return f"{obj.token[:4]}...{obj.token[-4:]}"
        return obj.token[:4] + "..."
    masked_token.short_description = 'Token'
    
    def exam_link(self, obj):
        """Create link to exam in admin"""
        url = reverse('admin:exams_exam_change', args=[obj.exam.id])
        return format_html('<a href="{}">{}</a>', url, obj.exam.title)
    exam_link.short_description = 'Exam'
    
    def student_name(self, obj):
        """Display student full name as per specification (concatenation of first_name and last_name)"""
        name = f"{obj.student.first_name} {obj.student.last_name}".strip()
        return name or obj.student.username
    student_name.short_description = 'Student Name'
    
    def student_email(self, obj):
        """Display student email"""
        return obj.student.email
    student_email.short_description = 'Student Email'
    
    def status_display(self, obj):
        """Display token status with color coding for better visualization"""
        if obj.is_used:
            return format_html('<span style="color: #d63384; font-weight: bold;">●</span> Used')
        elif obj.is_expired():
            return format_html('<span style="color: #fd7e14; font-weight: bold;">●</span> Expired')
        elif obj.is_valid():
            return format_html('<span style="color: #198754; font-weight: bold;">●</span> Valid')
        else:
            return format_html('<span style="color: #6c757d; font-weight: bold;">●</span> Inactive')
    status_display.short_description = 'Status'
    
    def time_remaining_display(self, obj):
        """Show time remaining for token validity"""
        if obj.is_used:
            return format_html('<span style="color: #6c757d;">N/A (Used)</span>')
        
        now = timezone.now()
        if now > obj.valid_until:
            expired_time = now - obj.valid_until
            return format_html('<span style="color: #d63384;">Expired {} ago</span>', expired_time)
        elif now < obj.valid_from:
            starts_in = obj.valid_from - now
            return format_html('<span style="color: #0d6efd;">Starts in {}</span>', starts_in)
        else:
            remaining = obj.valid_until - now
            return format_html('<span style="color: #198754;">{} remaining</span>', remaining)
    time_remaining_display.short_description = 'Time Status'
    
    def validation_url(self, obj):
        """Show the validation URL for the token"""
        if obj.token:
            url = f"/api/exams/access/{obj.token}/"
            return format_html('<code style="background: #f8f9fa; padding: 2px 4px;">{}</code>', url)
        return "No token"
    validation_url.short_description = 'Validation URL'
    
    # Admin actions for bulk operations
    actions = ['mark_as_used', 'mark_as_unused', 'cleanup_expired']
    
    def mark_as_used(self, request, queryset):
        """Admin action to mark tokens as used"""
        updated = queryset.update(is_used=True, used_at=timezone.now())
        self.message_user(
            request, 
            f'{updated} token{"s" if updated != 1 else ""} marked as used.'
        )
    mark_as_used.short_description = "Mark selected tokens as used"
    
    def mark_as_unused(self, request, queryset):
        """Admin action to mark tokens as unused (for testing purposes)"""
        updated = queryset.update(is_used=False, used_at=None)
        self.message_user(
            request, 
            f'{updated} token{"s" if updated != 1 else ""} marked as unused.'
        )
    mark_as_unused.short_description = "Mark selected tokens as unused (testing only)"
    
    def cleanup_expired(self, request, queryset):
        """Admin action to delete expired tokens"""
        expired_tokens = queryset.filter(valid_until__lt=timezone.now())
        count = expired_tokens.count()
        if count > 0:
            expired_tokens.delete()
            self.message_user(
                request,
                f'Cleaned up {count} expired token{"s" if count != 1 else ""}.'
            )
        else:
            self.message_user(request, 'No expired tokens found in selection.')
    cleanup_expired.short_description = "Delete expired tokens from selection"
    
    def get_queryset(self, request):
        """Optimize database queries"""
        return super().get_queryset(request).select_related('exam', 'student')


# Customize admin site headers and titles
admin.site.site_header = "Secure Exam Access Management"
admin.site.site_title = "Exam Access Admin"
admin.site.index_title = "Exam Access Control Panel"

# Add admin documentation
admin.site.site_url = "/api/"  # Link to API root from admin