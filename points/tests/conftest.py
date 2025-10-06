"""Shared fixtures for points app tests."""

import pytest
from django.contrib.auth import get_user_model


@pytest.fixture
def user():
    """Create a test user."""
    return get_user_model().objects.create_user(
        username="testuser", email="test@example.com", password="password123"
    )


@pytest.fixture
def tag():
    """Create a test tag."""
    from points.models import Tag

    return Tag.objects.create(name="test-tag")


@pytest.fixture
def default_tag():
    """Create a default tag."""
    from points.models import Tag

    return Tag.objects.create(name="default", is_default=True)


@pytest.fixture
def point_source(user, tag):
    """Create a test point source."""
    from points.models import PointSource

    source = PointSource.objects.create(
        user_profile=user, initial_points=100, remaining_points=100
    )
    source.tags.add(tag)
    return source
