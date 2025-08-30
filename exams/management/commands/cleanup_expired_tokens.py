from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.db import transaction
from exams.models import ExamAccessToken
from exams.services import ExamTokenService
import sys


class Command(BaseCommand):
    """
    Management command to clean up expired tokens as per specification:
    "Create a management command or Celery task to clean up expired tokens (valid_until < current time)"
    """
    help = 'Clean up expired exam access tokens'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be deleted without actually deleting',
        )
        parser.add_argument(
            '--days',
            type=int,
            default=0,
            help='Delete tokens expired more than X days ago (default: 0 - all expired)',
        )
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Show detailed information about deleted tokens',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Skip confirmation prompt',
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=1000,
            help='Process tokens in batches of this size (default: 1000)',
        )
    
    def handle(self, *args, **options):
        dry_run = options['dry_run']
        days = options['days']
        verbose = options['verbose'] or options['verbosity'] > 1
        force = options['force']
        batch_size = options['batch_size']
        
        self.stdout.write(
            self.style.HTTP_INFO('=== Exam Access Token Cleanup ===\n')
        )
        
        now = timezone.now()
        cutoff_date = now - timezone.timedelta(days=days) if days > 0 else now
        
        # Find expired tokens
        expired_tokens = ExamAccessToken.objects.filter(
            valid_until__lt=cutoff_date
        ).select_related('exam', 'student').order_by('valid_until')
        
        if not expired_tokens.exists():
            self.stdout.write(
                self.style.SUCCESS('No expired tokens found.')
            )
            return
        
        count = expired_tokens.count()
        
        # Display summary
        self.stdout.write(f'Found {count} expired tokens to clean up:')
        
        if days > 0:
            self.stdout.write(f'  - Tokens expired more than {days} days ago')
        else:
            self.stdout.write('  - All expired tokens')
            
        self.stdout.write(f'  - Cutoff date: {cutoff_date.strftime("%Y-%m-%d %H:%M:%S %Z")}\n')
        
        # Show detailed information if verbose or dry-run
        if verbose or dry_run:
            self.stdout.write('Token details:')
            self.stdout.write('-' * 80)
            
            display_count = min(count, 50)  # Limit display for readability
            
            for token in expired_tokens[:display_count]:
                expired_duration = now - token.valid_until
                days_expired = expired_duration.days
                hours_expired = expired_duration.seconds // 3600
                
                status = "USED" if token.is_used else "UNUSED"
                
                self.stdout.write(
                    f'  • {token.exam.title[:30]:<30} | '
                    f'{token.student.username:<15} | '
                    f'{status:<6} | '
                    f'Expired {days_expired}d {hours_expired}h ago'
                )
            
            if count > display_count:
                remaining = count - display_count
                self.stdout.write(f'  ... and {remaining} more tokens')
            
            self.stdout.write('-' * 80)
        
        # Token statistics
        total_tokens = ExamAccessToken.objects.count()
        used_expired = expired_tokens.filter(is_used=True).count()
        unused_expired = expired_tokens.filter(is_used=False).count()
        
        self.stdout.write('\nStatistics:')
        self.stdout.write(f'  - Total tokens in database: {total_tokens}')
        self.stdout.write(f'  - Expired tokens to delete: {count}')
        self.stdout.write(f'    • Used expired tokens: {used_expired}')
        self.stdout.write(f'    • Unused expired tokens: {unused_expired}')
        self.stdout.write(f'  - Tokens after cleanup: {total_tokens - count}')
        
        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f'\nDRY RUN: Would delete {count} expired tokens. '
                    'Run without --dry-run to actually delete them.'
                )
            )
            return
        
        # Confirmation prompt (unless forced or in quiet mode)
        if not force and options.get('verbosity', 1) > 0:
            self.stdout.write('\n' + '=' * 50)
            try:
                confirm = input(
                    f'Are you sure you want to permanently delete {count} expired tokens? [y/N]: '
                )
                if confirm.lower() not in ['y', 'yes']:
                    self.stdout.write(self.style.WARNING('Operation cancelled.'))
                    return
            except KeyboardInterrupt:
                self.stdout.write(self.style.WARNING('\nOperation cancelled by user.'))
                return
        
        # Perform cleanup in batches to avoid memory issues with large datasets
        self.stdout.write('\nCleaning up expired tokens...')
        
        try:
            total_deleted = 0
            
            while True:
                with transaction.atomic():
                    # Get batch of expired tokens
                    batch_ids = list(
                        ExamAccessToken.objects.filter(
                            valid_until__lt=cutoff_date
                        ).values_list('id', flat=True)[:batch_size]
                    )
                    
                    if not batch_ids:
                        break
                    
                    # Delete batch
                    deleted_info = ExamAccessToken.objects.filter(
                        id__in=batch_ids
                    ).delete()
                    
                    batch_deleted = deleted_info[0]
                    total_deleted += batch_deleted
                    
                    if verbose:
                        self.stdout.write(f'  Deleted batch: {batch_deleted} tokens')
            
            self.stdout.write(
                self.style.SUCCESS(
                    f'Successfully cleaned up {total_deleted} expired tokens!'
                )
            )
            
            # Final statistics
            remaining_tokens = ExamAccessToken.objects.count()
            self.stdout.write(f'\nFinal statistics:')
            self.stdout.write(f'   - Tokens remaining: {remaining_tokens}')
            self.stdout.write(f'   - Space saved: ~{total_deleted * 0.5:.1f} KB')
            
        except Exception as e:
            raise CommandError(f'Error during cleanup: {str(e)}')
        
        # Log the cleanup operation
        import logging
        logger = logging.getLogger('exams')
        logger.info(
            f'Cleaned up {total_deleted} expired tokens via management command '
            f'(days={days}, dry_run={dry_run})'
        )