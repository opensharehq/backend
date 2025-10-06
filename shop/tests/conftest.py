"""Shared pytest fixtures for shop tests."""

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile

from points.models import Tag
from shop.models import ShopItem


@pytest.fixture
def user(db):
    """Create a test user."""
    User = get_user_model()
    return User.objects.create_user(
        username="testuser", email="test@example.com", password="password123"
    )


@pytest.fixture
def tag(db):
    """Create a test tag."""
    return Tag.objects.create(name="test-tag")


@pytest.fixture
def default_tag(db):
    """Create a default tag."""
    return Tag.objects.create(name="default", is_default=True)


@pytest.fixture
def shop_item(db):
    """Create a basic shop item."""
    return ShopItem.objects.create(name="Test Item", description="Test", cost=100)


@pytest.fixture
def shop_item_with_stock(db):
    """Create a shop item with stock."""
    return ShopItem.objects.create(
        name="Test Item", description="Test", cost=100, stock=5
    )


@pytest.fixture
def image_file():
    """Create a test image file."""
    return SimpleUploadedFile(
        "test_image.jpg", b"file_content", content_type="image/jpeg"
    )
