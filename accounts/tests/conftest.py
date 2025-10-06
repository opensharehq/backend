"""Shared test fixtures for accounts app."""

import pytest
from django.contrib.auth import get_user_model

from accounts.models import UserProfile

User = get_user_model()


@pytest.fixture
def user(db):
    """Create a test user."""
    return User.objects.create_user(
        username="testuser",
        email="test@example.com",
        password="password123",
    )


@pytest.fixture
def authenticated_client(client, user):
    """Create an authenticated client."""
    client.login(username="testuser", password="password123")
    return client


@pytest.fixture
def user_with_profile(user):
    """Create a user with a profile."""
    UserProfile.objects.create(
        user=user,
        bio="Test bio",
        location="Test location",
        company="Test company",
    )
    return user
