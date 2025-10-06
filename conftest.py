"""
Root conftest.py for project-wide pytest configuration and fixtures.

This file provides shared fixtures and configuration for all test modules
in the fullsite project.
"""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client


@pytest.fixture
def user(db):
    """
    Create a test user.

    Returns:
        User: A test user with username 'testuser'

    """
    User = get_user_model()
    return User.objects.create_user(
        username="testuser",
        email="test@example.com",
        password="testpass123",
    )


@pytest.fixture
def admin_user(db):
    """
    Create an admin user.

    Returns:
        User: A superuser with username 'admin'

    """
    User = get_user_model()
    return User.objects.create_superuser(
        username="admin",
        email="admin@example.com",
        password="adminpass123",
    )


@pytest.fixture
def authenticated_client(user):
    """
    Create an authenticated client.

    Args:
        user: The user fixture

    Returns:
        Client: Django test client logged in as user

    """
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def admin_client(admin_user):
    """
    Create an authenticated admin client.

    Args:
        admin_user: The admin_user fixture

    Returns:
        Client: Django test client logged in as admin

    """
    client = Client()
    client.force_login(admin_user)
    return client


def pytest_configure(config):
    """Configure pytest with custom settings."""
    # Register markers programmatically (alternative to pyproject.toml)
    config.addinivalue_line("markers", "unit: Unit tests (fast, isolated tests)")
    config.addinivalue_line(
        "markers",
        "integration: Integration tests (tests that involve multiple components)",
    )
    config.addinivalue_line("markers", "model: Model layer tests")
    config.addinivalue_line("markers", "view: View layer tests")
    config.addinivalue_line("markers", "form: Form tests")
    config.addinivalue_line("markers", "service: Service layer tests")
    config.addinivalue_line("markers", "task: Background task tests")
    config.addinivalue_line("markers", "command: Management command tests")
    config.addinivalue_line("markers", "slow: Slow running tests")
