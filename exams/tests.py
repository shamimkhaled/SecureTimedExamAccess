
from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from datetime import timedelta
from unittest.mock import patch, MagicMock

from exams.models import Exam, ExamAccessToken
from exams.services import ExamTokenService


class ExamTokenServiceTest(TestCase):
    """Test the service layer for token operations"""
    
    def setUp(self):
        self.exam = Exam.objects.create(
            title='Test Programming Exam',
            start_time=timezone.now() + timedelta(hours=1),
            end_time=timezone.now() + timedelta(hours=3)
        )
        self.student = User.objects.create_user(
            username='teststudent',
            email='test@student.com',
            first_name='Test',
            last_name='Student'
        )
    
    def test_generate_secure_token(self):
        """Test that token generation produces unique, secure tokens"""
        token1 = ExamTokenService.generate_secure_token()
        token2 = ExamTokenService.generate_secure_token()
        
        # Tokens should be different
        self.assertNotEqual(token1, token2)
        
        # Tokens should be within specified length
        self.assertTrue(len(token1) <= 36)
        self.assertTrue(len(token2) <= 36)
        
        # Tokens should contain only safe characters
        import string
        safe_chars = string.ascii_letters + string.digits + '-_'
        self.assertTrue(all(c in safe_chars for c in token1))
        self.assertTrue(all(c in safe_chars for c in token2))
    
    def test_generate_exam_token_success(self):
        """Test successful token generation"""
        result = ExamTokenService.generate_exam_token(
            exam_id=self.exam.id,
            student_id=self.student.id,
            valid_minutes=30
        )
        
        self.assertTrue(result['success'])
        self.assertIn('token', result)
        self.assertEqual(result['status_code'], 201)
        
        # Verify token was created in database
        token_obj = ExamAccessToken.objects.get(token=result['token'])
        self.assertEqual(token_obj.exam, self.exam)
        self.assertEqual(token_obj.student, self.student)
        self.assertFalse(token_obj.is_used)
    
    def test_generate_exam_token_invalid_inputs(self):
        """Test token generation with invalid inputs as per specification"""
        # Negative valid_minutes
        result = ExamTokenService.generate_exam_token(
            exam_id=self.exam.id,
            student_id=self.student.id,
            valid_minutes=-5
        )
        self.assertFalse(result['success'])
        self.assertEqual(result['status_code'], 400)
        
        # Non-existent exam
        result = ExamTokenService.generate_exam_token(
            exam_id=99999,
            student_id=self.student.id,
            valid_minutes=30
        )
        self.assertFalse(result['success'])
        self.assertEqual(result['status_code'], 400)
        self.assertEqual(result['error'], 'Invalid exam or student')
        
        # Non-existent student
        result = ExamTokenService.generate_exam_token(
            exam_id=self.exam.id,
            student_id=99999,
            valid_minutes=30
        )
        self.assertFalse(result['success'])
        self.assertEqual(result['status_code'], 400)
        self.assertEqual(result['error'], 'Invalid exam or student')
    
    def test_duplicate_token_generation(self):
        """Test duplicate token generation handling as per specification"""
        # Generate first token
        result1 = ExamTokenService.generate_exam_token(
            exam_id=self.exam.id,
            student_id=self.student.id,
            valid_minutes=30
        )
        self.assertTrue(result1['success'])
        
        # Attempt duplicate generation
        result2 = ExamTokenService.generate_exam_token(
            exam_id=self.exam.id,
            student_id=self.student.id,
            valid_minutes=30
        )
        self.assertFalse(result2['success'])
        self.assertEqual(result2['status_code'], 400)
        self.assertEqual(result2['error'], 'Token already exists for this student and exam')
    
    def test_token_regeneration_bonus_feature(self):
        """Test token regeneration bonus feature"""
        # Generate first token
        result1 = ExamTokenService.generate_exam_token(
            exam_id=self.exam.id,
            student_id=self.student.id,
            valid_minutes=30
        )
        old_token = result1['token']
        
        # Regenerate token
        result2 = ExamTokenService.generate_exam_token(
            exam_id=self.exam.id,
            student_id=self.student.id,
            valid_minutes=30,
            regenerate=True
        )
        
        self.assertTrue(result2['success'])
        self.assertNotEqual(old_token, result2['token'])
        
        # Old token should be marked as used
        old_token_obj = ExamAccessToken.objects.get(token=old_token)
        self.assertTrue(old_token_obj.is_used)
    
    def test_validate_token_success(self):
        """Test successful token validation as per specification"""
        # Generate token
        result = ExamTokenService.generate_exam_token(
            exam_id=self.exam.id,
            student_id=self.student.id,
            valid_minutes=30
        )
        token = result['token']
        
        # Validate token
        validation_result = ExamTokenService.validate_and_use_token(token)
        
        self.assertTrue(validation_result['success'])
        self.assertEqual(validation_result['status_code'], 200)
        self.assertIn('exam', validation_result)
        self.assertIn('student', validation_result)
        
        # Check expected response format as per specification
        self.assertEqual(validation_result['exam']['title'], self.exam.title)
        expected_name = f"{self.student.first_name} {self.student.last_name}".strip()
        self.assertEqual(validation_result['student']['name'], expected_name)
        self.assertEqual(validation_result['student']['email'], self.student.email)
        
        # Token should be marked as used
        token_obj = ExamAccessToken.objects.get(token=token)
        self.assertTrue(token_obj.is_used)
        self.assertIsNotNone(token_obj.used_at)
    
    def test_validate_token_already_used(self):
        """Test validation of already used token as per specification"""
        # Generate and use token
        result = ExamTokenService.generate_exam_token(
            exam_id=self.exam.id,
            student_id=self.student.id,
            valid_minutes=30
        )
        token = result['token']
        ExamTokenService.validate_and_use_token(token)
        
        # Attempt to validate again
        validation_result = ExamTokenService.validate_and_use_token(token)
        
        self.assertFalse(validation_result['success'])
        self.assertEqual(validation_result['status_code'], 403)
        self.assertEqual(validation_result['error'], 'Token already used')
    
    def test_validate_expired_token(self):
        """Test validation of expired token as per specification"""
        # Create expired token manually
        token_obj = ExamAccessToken.objects.create(
            exam=self.exam,
            student=self.student,
            token=ExamTokenService.generate_secure_token(),
            valid_from=timezone.now() - timedelta(hours=2),
            valid_until=timezone.now() - timedelta(hours=1),
            is_used=False
        )
        
        validation_result = ExamTokenService.validate_and_use_token(token_obj.token)
        
        self.assertFalse(validation_result['success'])
        self.assertEqual(validation_result['status_code'], 403)
        self.assertEqual(validation_result['error'], 'This access link has expired')
    
    def test_validate_invalid_token(self):
        """Test validation of non-existent token as per specification"""
        validation_result = ExamTokenService.validate_and_use_token('invalid-token-12345')
        
        self.assertFalse(validation_result['success'])
        self.assertEqual(validation_result['status_code'], 403)
        self.assertEqual(validation_result['error'], 'Invalid token')
    
    def test_cleanup_expired_tokens(self):
        """Test cleanup functionality as per specification"""
        # Create expired token
        ExamAccessToken.objects.create(
            exam=self.exam,
            student=self.student,
            token='expired-token-123',
            valid_from=timezone.now() - timedelta(hours=2),
            valid_until=timezone.now() - timedelta(hours=1),
            is_used=False
        )
        
        # Create valid token
        student2 = User.objects.create_user(username='student2')
        ExamAccessToken.objects.create(
            exam=self.exam,
            student=student2,
            token='valid-token-456',
            valid_from=timezone.now(),
            valid_until=timezone.now() + timedelta(hours=1),
            is_used=False
        )
        
        initial_count = ExamAccessToken.objects.count()
        deleted_count = ExamTokenService.cleanup_expired_tokens()
        final_count = ExamAccessToken.objects.count()
        
        self.assertEqual(deleted_count, 1)
        self.assertEqual(final_count, initial_count - 1)
        self.assertFalse(ExamAccessToken.objects.filter(token='expired-token-123').exists())
        self.assertTrue(ExamAccessToken.objects.filter(token='valid-token-456').exists())


class ExamAPIEndpointTest(TestCase):
    """Test the API endpoints as per specification"""
    
    def setUp(self):
        self.client = APIClient()
        
        # Create instructor and student
        self.instructor = User.objects.create_user(
            username='instructor',
            email='instructor@test.com',
            is_staff=True
        )
        self.student = User.objects.create_user(
            username='student',
            email='student@test.com',
            first_name='John',
            last_name='Doe'
        )
        
        # Create exam
        self.exam = Exam.objects.create(
            title='Final Python Exam',
            start_time=timezone.now() + timedelta(hours=1),
            end_time=timezone.now() + timedelta(hours=3)
        )
    
    def test_generate_token_success(self):
        """Test POST /api/exams/<exam_id>/generate-token/ success case"""
        self.client.force_authenticate(user=self.instructor)
        
        url = reverse('exams:generate_token', kwargs={'exam_id': self.exam.id})
        data = {
            'student_id': self.student.id,
            'valid_minutes': 10
        }
        
        response = self.client.post(url, data, format='json')
        
        # Expected: 201 Created as per specification
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('token', response.data)
        self.assertEqual(response.data['message'], 'Token generated successfully')
    
    def test_generate_token_unauthorized(self):
        """Test unauthorized access to token generation"""
        regular_user = User.objects.create_user(username='regular', email='regular@test.com')
        self.client.force_authenticate(user=regular_user)
        
        url = reverse('exams:generate_token', kwargs={'exam_id': self.exam.id})
        data = {
            'student_id': self.student.id,
            'valid_minutes': 10
        }
        
        response = self.client.post(url, data, format='json')
        
        # Expected: 403 Forbidden as per specification
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data['detail'], 'Unauthorized')
    
    def test_generate_token_invalid_exam(self):
        """Test token generation for non-existent exam"""
        self.client.force_authenticate(user=self.instructor)
        
        url = reverse('exams:generate_token', kwargs={'exam_id': 99999})
        data = {
            'student_id': self.student.id,
            'valid_minutes': 10
        }
        
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
    
    def test_generate_token_invalid_student(self):
        """Test token generation for non-existent student"""
        self.client.force_authenticate(user=self.instructor)
        
        url = reverse('exams:generate_token', kwargs={'exam_id': self.exam.id})
        data = {
            'student_id': 99999,
            'valid_minutes': 10
        }
        
        response = self.client.post(url, data, format='json')
        
        # Expected: 400 Bad Request as per specification
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['detail'], 'Invalid exam or student')
    
    def test_validate_token_success(self):
        """Test GET /api/exams/access/<token>/ success case"""
        # Generate token first
        self.client.force_authenticate(user=self.instructor)
        generate_url = reverse('exams:generate_token', kwargs={'exam_id': self.exam.id})
        generate_data = {
            'student_id': self.student.id,
            'valid_minutes': 10
        }
        generate_response = self.client.post(generate_url, generate_data, format='json')
        token = generate_response.data['token']
        
        # Validate token (public endpoint - no authentication required)
        self.client.force_authenticate(user=None)
        validate_url = reverse('exams:validate_token', kwargs={'token': token})
        
        response = self.client.get(validate_url)
        
        # Expected: 200 OK as per specification
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('exam', response.data)
        self.assertIn('student', response.data)
        
        # Check response format as per specification
        self.assertEqual(response.data['exam']['title'], 'Final Python Exam')
        self.assertEqual(response.data['student']['name'], 'John Doe')
        self.assertEqual(response.data['student']['email'], 'student@test.com')
    
    def test_validate_invalid_token(self):
        """Test validation of invalid token"""
        url = reverse('exams:validate_token', kwargs={'token': 'invalid-token'})
        
        response = self.client.get(url)
        
        # Expected: 403 Forbidden as per specification
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data['detail'], 'Invalid token')
    
    def test_token_single_use_enforcement(self):
        """Test that tokens can only be used once as per specification"""
        # Generate token
        self.client.force_authenticate(user=self.instructor)
        generate_url = reverse('exams:generate_token', kwargs={'exam_id': self.exam.id})
        generate_data = {
            'student_id': self.student.id,
            'valid_minutes': 10
        }
        generate_response = self.client.post(generate_url, generate_data, format='json')
        token = generate_response.data['token']
        
        # Use token first time
        self.client.force_authenticate(user=None)
        validate_url = reverse('exams:validate_token', kwargs={'token': token})
        response1 = self.client.get(validate_url)
        self.assertEqual(response1.status_code, status.HTTP_200_OK)
        
        # Try to use token second time
        response2 = self.client.get(validate_url)
        self.assertEqual(response2.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response2.data['detail'], 'Token already used')


class ModelTest(TestCase):
    """Test model functionality and constraints"""
    
    def setUp(self):
        self.exam = Exam.objects.create(
            title='Test Exam',
            start_time=timezone.now(),
            end_time=timezone.now() + timedelta(hours=2)
        )
        self.student = User.objects.create_user(username='student')
    
    def test_exam_model_constraints(self):
        """Test exam model validation"""
        # Test that end_time must be after start_time
        with self.assertRaises(Exception):
            Exam.objects.create(
                title='Invalid Exam',
                start_time=timezone.now(),
                end_time=timezone.now() - timedelta(hours=1)
            )
    
    def test_unique_constraint_enforcement(self):
        """Test uniqueness of (exam, student) pair as per specification"""
        # Create first token
        ExamAccessToken.objects.create(
            exam=self.exam,
            student=self.student,
            token='token123',
            valid_from=timezone.now(),
            valid_until=timezone.now() + timedelta(hours=1)
        )
        
        # Attempt to create duplicate
        with self.assertRaises(Exception):
            ExamAccessToken.objects.create(
                exam=self.exam,
                student=self.student,
                token='token456',
                valid_from=timezone.now(),
                valid_until=timezone.now() + timedelta(hours=1)
            )
    
    def test_token_status_methods(self):
        """Test token status helper methods"""
        # Create valid token
        token = ExamAccessToken.objects.create(
            exam=self.exam,
            student=self.student,
            token='test-token',
            valid_from=timezone.now() - timedelta(minutes=5),
            valid_until=timezone.now() + timedelta(minutes=5)
        )
        
        self.assertTrue(token.is_valid())
        self.assertFalse(token.is_expired())
        self.assertFalse(token.is_not_yet_valid())
        
        # Mark as used
        token.is_used = True
        self.assertFalse(token.is_valid())
        
        # Test expired token
        expired_token = ExamAccessToken.objects.create(
            exam=self.exam,
            student=User.objects.create_user(username='student2'),
            token='expired-token',
            valid_from=timezone.now() - timedelta(hours=2),
            valid_until=timezone.now() - timedelta(hours=1)
        )
        
        self.assertTrue(expired_token.is_expired())
        self.assertFalse(expired_token.is_valid())


class ConcurrencyTest(TestCase):
    """Test concurrent access scenarios"""
    
    def setUp(self):
        self.exam = Exam.objects.create(
            title='Concurrent Test Exam',
            start_time=timezone.now(),
            end_time=timezone.now() + timedelta(hours=2)
        )
        self.student = User.objects.create_user(username='concurrent_student')
    
    def test_atomic_token_validation(self):
        """Test that token validation prevents race conditions"""
        # This test simulates concurrent access attempts
        token = ExamAccessToken.objects.create(
            exam=self.exam,
            student=self.student,
            token='concurrent-token',
            valid_from=timezone.now(),
            valid_until=timezone.now() + timedelta(hours=1)
        )
        
        # First validation should succeed
        result1 = ExamTokenService.validate_and_use_token(token.token)
        self.assertTrue(result1['success'])
        
        # Second validation should fail due to atomic operation
        result2 = ExamTokenService.validate_and_use_token(token.token)
        self.assertFalse(result2['success'])
        self.assertEqual(result2['error'], 'Token already used')