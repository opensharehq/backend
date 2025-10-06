"""Test cases for shop models."""

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from points.models import Tag
from shop.models import Redemption, ShopItem


class ShopItemModelTests(TestCase):
    """Test cases for ShopItem model."""

    def setUp(self):
        """Set up test fixtures."""
        self.tag = Tag.objects.create(name="test-tag")

    def test_shop_item_str(self):
        """Test string representation of ShopItem."""
        item = ShopItem.objects.create(
            name="Test Item", description="Test description", cost=100
        )

        assert str(item) == "Test Item - 100 pts"

    def test_shop_item_creation(self):
        """Test creating a shop item."""
        item = ShopItem.objects.create(
            name="Test Item",
            description="Test description",
            cost=100,
            stock=10,
            is_active=True,
        )

        assert item.name == "Test Item"
        assert item.description == "Test description"
        assert item.cost == 100
        assert item.stock == 10
        assert item.is_active is True

    def test_shop_item_unlimited_stock(self):
        """Test creating item with unlimited stock."""
        item = ShopItem.objects.create(
            name="Unlimited Item", description="Test", cost=50, stock=None
        )

        assert item.stock is None

    def test_shop_item_with_allowed_tags(self):
        """Test creating item with allowed tags."""
        tag1 = Tag.objects.create(name="tag1")
        tag2 = Tag.objects.create(name="tag2")

        item = ShopItem.objects.create(name="Tagged Item", description="Test", cost=50)
        item.allowed_tags.set([tag1, tag2])

        assert item.allowed_tags.count() == 2
        assert tag1 in item.allowed_tags.all()
        assert tag2 in item.allowed_tags.all()

    def test_shop_item_default_is_active(self):
        """Test that is_active defaults to True."""
        item = ShopItem.objects.create(name="Test", description="Test", cost=10)

        assert item.is_active is True

    def test_shop_item_timestamps(self):
        """Test that created_at and updated_at are set."""
        item = ShopItem.objects.create(name="Test", description="Test", cost=10)

        assert item.created_at is not None
        assert item.updated_at is not None

    def test_shop_item_with_image(self):
        """Test creating shop item with image."""
        image_file = SimpleUploadedFile(
            "test_image.jpg", b"file_content", content_type="image/jpeg"
        )
        item = ShopItem.objects.create(
            name="Item with Image",
            description="Test",
            cost=100,
            image=image_file,
        )

        assert item.image is not None
        assert "test_image" in item.image.name
        assert item.image.name.startswith("shop/items/")

    def test_shop_item_without_image(self):
        """Test creating shop item without image (null/blank)."""
        item = ShopItem.objects.create(
            name="Item without Image", description="Test", cost=50
        )

        assert not item.image

    def test_shop_item_image_upload_path(self):
        """Test that image is uploaded to correct path."""
        image_file = SimpleUploadedFile(
            "product.png", b"image_data", content_type="image/png"
        )
        item = ShopItem.objects.create(
            name="Path Test", description="Test", cost=75, image=image_file
        )

        assert item.image.name.startswith("shop/items/")


class RedemptionModelTests(TestCase):
    """Test cases for Redemption model."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = get_user_model().objects.create_user(
            username="testuser", email="test@example.com", password="password123"
        )
        self.item = ShopItem.objects.create(
            name="Test Item", description="Test", cost=100
        )

    def test_redemption_str(self):
        """Test string representation of Redemption."""
        redemption = Redemption.objects.create(
            user_profile=self.user, item=self.item, points_cost_at_redemption=100
        )

        assert str(redemption) == "testuser redeemed Test Item"

    def test_redemption_creation(self):
        """Test creating a redemption."""
        redemption = Redemption.objects.create(
            user_profile=self.user,
            item=self.item,
            points_cost_at_redemption=100,
            status=Redemption.StatusChoices.COMPLETED,
        )

        assert redemption.user_profile == self.user
        assert redemption.item == self.item
        assert redemption.points_cost_at_redemption == 100
        assert redemption.status == "COMPLETED"

    def test_redemption_default_status(self):
        """Test that status defaults to PENDING."""
        redemption = Redemption.objects.create(
            user_profile=self.user, item=self.item, points_cost_at_redemption=100
        )

        assert redemption.status == "PENDING"

    def test_redemption_ordering(self):
        """Test that redemptions are ordered by created_at desc."""
        redemption1 = Redemption.objects.create(
            user_profile=self.user, item=self.item, points_cost_at_redemption=100
        )
        redemption2 = Redemption.objects.create(
            user_profile=self.user, item=self.item, points_cost_at_redemption=50
        )

        redemptions = Redemption.objects.all()

        assert redemptions[0] == redemption2
        assert redemptions[1] == redemption1

    def test_redemption_with_transaction(self):
        """Test redemption with associated transaction."""
        from points.models import PointTransaction

        transaction = PointTransaction.objects.create(
            user_profile=self.user,
            points=-100,
            transaction_type=PointTransaction.TransactionType.SPEND,
            description="Test",
        )

        redemption = Redemption.objects.create(
            user_profile=self.user,
            item=self.item,
            points_cost_at_redemption=100,
            transaction=transaction,
        )

        assert redemption.transaction == transaction
        assert transaction.redemption == redemption
