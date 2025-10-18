"""Integration tests for accounts app workflows."""

from datetime import date

from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.test import Client, TestCase
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from accounts.models import Education, UserProfile, WorkExperience


class UserRegistrationFlowTests(TestCase):
    """Test complete user registration workflow."""

    def setUp(self):
        """Set up test fixtures."""
        self.client = Client()

    def test_complete_user_registration_and_login_flow(self):
        """Test user can register, then login successfully."""
        # Step 1: Register new user
        signup_url = reverse("accounts:sign_up")
        signup_data = {
            "username": "newuser",
            "email": "newuser@example.com",
            "password1": "SecurePass123!",
            "password2": "SecurePass123!",
        }

        response = self.client.post(signup_url, signup_data)

        # Verify redirect to homepage after registration
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("homepage:index"))

        # Verify user was created
        User = get_user_model()
        user = User.objects.get(username="newuser")
        self.assertEqual(user.email, "newuser@example.com")
        self.assertTrue(user.is_active)

        # Step 2: Login with new credentials
        # Use Django's test client login method for integration testing
        login_successful = self.client.login(
            username="newuser", password="SecurePass123!"
        )
        self.assertTrue(login_successful)

        # Step 3: Access protected profile page
        profile_url = reverse("accounts:profile")
        response = self.client.get(profile_url)

        self.assertEqual(response.status_code, 200)
        self.assertIn("newuser", response.content.decode())

    def test_user_registration_with_invalid_data_shows_errors(self):
        """Test registration with mismatched passwords shows errors."""
        signup_url = reverse("accounts:sign_up")
        signup_data = {
            "username": "testuser",
            "email": "test@example.com",
            "password1": "SecurePass123!",
            "password2": "DifferentPass456!",  # Mismatched password
        }

        response = self.client.post(signup_url, signup_data)

        # Should not create user
        User = get_user_model()
        self.assertFalse(User.objects.filter(username="testuser").exists())

        # Should show form errors
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            "密码" in response.content.decode()
            or "password" in response.content.decode()
        )

    def test_duplicate_username_registration_fails(self):
        """Test cannot register with existing username."""
        User = get_user_model()
        User.objects.create_user(
            username="existinguser",
            email="existing@example.com",
            password="password123",
        )

        signup_url = reverse("accounts:sign_up")
        signup_data = {
            "username": "existinguser",  # Duplicate username
            "email": "newemail@example.com",
            "password1": "SecurePass123!",
            "password2": "SecurePass123!",
        }

        response = self.client.post(signup_url, signup_data)

        # Should not create duplicate user
        self.assertEqual(User.objects.filter(username="existinguser").count(), 1)

        # Should show error
        self.assertEqual(response.status_code, 200)


class ProfileManagementFlowTests(TestCase):
    """Test complete profile management workflow."""

    def setUp(self):
        """Set up test fixtures."""
        self.client = Client()
        User = get_user_model()
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        self.client.force_login(self.user)

    def test_complete_profile_editing_flow(self):
        """Test user can view and edit their profile."""
        # Step 1: View empty profile
        profile_url = reverse("accounts:profile")
        response = self.client.get(profile_url)

        self.assertEqual(response.status_code, 200)
        self.assertIn("testuser", response.content.decode())

        # Step 2: Edit profile with complete information
        edit_url = reverse("accounts:profile_edit")
        profile_data = {
            "bio": "Software developer passionate about open source",
            "birth_date": "1990-01-15",
            "github_url": "https://github.com/testuser",
            "homepage_url": "https://testuser.dev",
            "blog_url": "https://blog.testuser.dev",
            "twitter_url": "https://twitter.com/testuser",
            "linkedin_url": "https://linkedin.com/in/testuser",
            "company": "Tech Corp",
            "location": "Beijing, China",
            # Formset management data for work experiences
            "work_experiences-TOTAL_FORMS": "0",
            "work_experiences-INITIAL_FORMS": "0",
            "work_experiences-MIN_NUM_FORMS": "0",
            "work_experiences-MAX_NUM_FORMS": "1000",
            # Formset management data for educations
            "educations-TOTAL_FORMS": "0",
            "educations-INITIAL_FORMS": "0",
            "educations-MIN_NUM_FORMS": "0",
            "educations-MAX_NUM_FORMS": "1000",
            # Formset management data for shipping addresses
            "shipping_addresses-TOTAL_FORMS": "0",
            "shipping_addresses-INITIAL_FORMS": "0",
            "shipping_addresses-MIN_NUM_FORMS": "0",
            "shipping_addresses-MAX_NUM_FORMS": "1000",
        }

        response = self.client.post(edit_url, profile_data)

        # Verify redirect to profile
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("accounts:profile"))

        # Step 3: Verify profile was updated
        self.user.refresh_from_db()
        profile = self.user.profile

        self.assertEqual(profile.bio, "Software developer passionate about open source")
        self.assertEqual(profile.birth_date, date(1990, 1, 15))
        self.assertEqual(profile.github_url, "https://github.com/testuser")
        self.assertEqual(profile.company, "Tech Corp")
        self.assertEqual(profile.location, "Beijing, China")

        # Step 4: View updated profile
        response = self.client.get(profile_url)
        content = response.content.decode()

        self.assertIn("Software developer", content)
        self.assertIn("Tech Corp", content)
        self.assertIn("Beijing", content)

    def test_add_work_experience_and_education(self):
        """Test user can add work experience and education to profile."""
        # Ensure profile exists
        UserProfile.objects.get_or_create(user=self.user)

        # Add work experience
        WorkExperience.objects.create(
            profile=self.user.profile,
            company_name="Awesome Tech Inc",
            title="Senior Developer",
            start_date=date(2020, 1, 1),
            end_date=None,  # Currently working
            description="Leading backend development team",
        )

        # Add education
        Education.objects.create(
            profile=self.user.profile,
            institution_name="Tech University",
            degree="本科",
            field_of_study="计算机科学",
            start_date=date(2015, 9, 1),
            end_date=date(2019, 6, 30),
        )

        # Verify work experience was added
        self.assertEqual(self.user.profile.work_experiences.count(), 1)
        work = self.user.profile.work_experiences.first()
        self.assertEqual(work.company_name, "Awesome Tech Inc")
        self.assertEqual(work.title, "Senior Developer")
        self.assertTrue(work.end_date is None)  # Still working

        # Verify education was added
        self.assertEqual(self.user.profile.educations.count(), 1)
        edu = self.user.profile.educations.first()
        self.assertEqual(edu.institution_name, "Tech University")
        self.assertEqual(edu.degree, "本科")
        self.assertEqual(edu.field_of_study, "计算机科学")


class PasswordResetFlowTests(TestCase):
    """Test complete password reset workflow."""

    def setUp(self):
        """Set up test fixtures."""
        self.client = Client()
        User = get_user_model()
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="oldpassword123",
        )

    def test_complete_password_reset_flow(self):
        """Test user can reset password via email."""
        # Step 1: Request password reset
        reset_request_url = reverse("accounts:password_reset_request")
        response = self.client.post(reset_request_url, {"email": "test@example.com"})

        # Verify redirect to done page
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("accounts:password_reset_done"))

        # Note: Email is sent via async task, so we don't check mail.outbox here
        # In a real integration test environment, we would need to run the worker
        # or use synchronous task execution

        # Step 2: Simulate token generation (as if email was received)
        # In real flow, user would click link in email
        uid = urlsafe_base64_encode(force_bytes(self.user.pk))
        token = default_token_generator.make_token(self.user)

        # Step 3: Access password reset confirm page
        reset_confirm_url = reverse(
            "accounts:password_reset_confirm",
            kwargs={"uidb64": uid, "token": token},
        )
        response = self.client.get(reset_confirm_url)

        self.assertEqual(response.status_code, 200)

        # Step 4: Submit new password
        new_password_data = {
            "new_password1": "NewSecurePass123!",
            "new_password2": "NewSecurePass123!",
        }

        response = self.client.post(reset_confirm_url, new_password_data)

        # Should redirect after successful reset
        self.assertEqual(response.status_code, 302)

        # Step 5: Verify can login with new password
        self.user.refresh_from_db()
        login_successful = self.client.login(
            username="testuser", password="NewSecurePass123!"
        )
        self.assertTrue(login_successful)

    def test_password_reset_with_invalid_email(self):
        """Test password reset request with non-existent email."""
        reset_request_url = reverse("accounts:password_reset_request")
        response = self.client.post(
            reset_request_url,
            {"email": "nonexistent@example.com"},
        )

        # Still redirects to done page (security: don't reveal if email exists)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("accounts:password_reset_done"))

        # No email should be sent
        self.assertEqual(len(mail.outbox), 0)


class PasswordChangeFlowTests(TestCase):
    """Test password change workflow for logged-in users."""

    def setUp(self):
        """Set up test fixtures."""
        self.client = Client()
        User = get_user_model()
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="oldpassword123",
        )
        self.client.force_login(self.user)

    def test_complete_password_change_flow(self):
        """Test user can change password while logged in."""
        # Step 1: Access password change page
        change_url = reverse("accounts:change_password")
        response = self.client.get(change_url)

        self.assertEqual(response.status_code, 200)

        # Step 2: Submit password change with correct old password
        change_data = {
            "old_password": "oldpassword123",
            "new_password1": "NewSecurePass456!",
            "new_password2": "NewSecurePass456!",
        }

        response = self.client.post(change_url, change_data)

        # Should redirect to profile
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("accounts:profile"))

        # Step 3: Logout
        self.client.logout()

        # Step 4: Login with new password
        login_successful = self.client.login(
            username="testuser", password="NewSecurePass456!"
        )
        self.assertTrue(login_successful)

        # Step 5: Verify old password no longer works
        self.client.logout()
        old_login_successful = self.client.login(
            username="testuser", password="oldpassword123"
        )
        self.assertFalse(old_login_successful)


class EmailChangeFlowTests(TestCase):
    """Test email change workflow for logged-in users."""

    def setUp(self):
        """Set up test fixtures."""
        self.client = Client()
        User = get_user_model()
        self.user = User.objects.create_user(
            username="testuser",
            email="old@example.com",
            password="testpass123",
        )
        self.client.force_login(self.user)

    def test_complete_email_change_flow(self):
        """Test user can change their email address."""
        # Step 1: Access email change page
        change_url = reverse("accounts:change_email")
        response = self.client.get(change_url)

        self.assertEqual(response.status_code, 200)

        # Step 2: Submit new email with password
        change_data = {
            "email": "new@example.com",
            "password": "testpass123",
        }

        response = self.client.post(change_url, change_data)

        # Should redirect to profile
        self.assertEqual(response.status_code, 302)

        # Step 3: Verify email was changed
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "new@example.com")

    def test_email_change_to_existing_email_fails(self):
        """Test cannot change to an email already in use."""
        User = get_user_model()
        # Create another user with target email
        User.objects.create_user(
            username="otheruser",
            email="existing@example.com",
            password="password123",
        )

        change_url = reverse("accounts:change_email")
        change_data = {
            "email": "existing@example.com",
            "password": "testpass123",
        }

        response = self.client.post(change_url, change_data)

        # Should show error (status 200 = form with errors)
        self.assertEqual(response.status_code, 200)

        # Email should not change
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "old@example.com")
