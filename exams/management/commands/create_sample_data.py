from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta
from exams.models import Exam

class Command(BaseCommand):
    help = 'Creates sample data for development and testing'

    def handle(self, *args, **kwargs):
        # Create sample exams
        now = timezone.now()
        
        # Future exam
        Exam.objects.create(
            title='Python Programming Fundamentals',
            start_time=now + timedelta(days=1),
            end_time=now + timedelta(days=1, hours=2),
        )
        self.stdout.write(self.style.SUCCESS('Created future exam'))
        
        # Current exam (if needed for testing)
        Exam.objects.create(
            title='Web Development with Django',
            start_time=now - timedelta(minutes=30),
            end_time=now + timedelta(hours=1, minutes=30),
        )
        self.stdout.write(self.style.SUCCESS('Created current exam'))
        
        # Past exam
        Exam.objects.create(
            title='Database Design and SQL',
            start_time=now - timedelta(days=7),
            end_time=now - timedelta(days=7, hours=-2),
        )
        self.stdout.write(self.style.SUCCESS('Created past exam'))
        
        # Create sample users if they don't exist
        if not User.objects.filter(username='instructor').exists():
            instructor = User.objects.create_user(
                username='instructor',
                email='instructor@example.com',
                first_name='Shamim Khaled',
                last_name='Instructor',
                is_staff=True,
                is_superuser=True
            )
            instructor.set_password('instructor999')
            instructor.save()
            self.stdout.write(self.style.SUCCESS('Created instructor user'))
        
        # Create sample students
        student_data = [
            ('alice_student', 'alice@example.com', 'Alice', 'Johnson'),
            ('bob_student', 'bob@example.com', 'Bob', 'Smith'),
            ('carol_student', 'carol@example.com', 'Carol', 'Davis'),
        ]
        
        for username, email, first_name, last_name in student_data:
            if not User.objects.filter(username=username).exists():
                student = User.objects.create_user(
                    username=username,
                    email=email,
                    first_name=first_name,
                    last_name=last_name,
                )
                student.set_password('student999')
                student.save()
                self.stdout.write(
                    self.style.SUCCESS(f'Created student user: {username}')
                )
