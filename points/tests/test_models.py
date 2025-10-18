"""Tests for points models."""

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.db.models import F
from django.test import TestCase
from django.utils import timezone

from points.models import PointSource, PointTransaction, Tag

User = get_user_model()


class TagModelTests(TestCase):
    """Test cases for Tag model."""

    def test_tag_str(self):
        """Test string representation of Tag."""
        tag = Tag.objects.create(name="test-tag", description="Test description")

        self.assertEqual(str(tag), "test-tag")

    def test_tag_unique_name(self):
        """Test that tag names must be unique."""
        Tag.objects.create(name="unique-tag")

        with self.assertRaises(IntegrityError):
            Tag.objects.create(name="unique-tag")

    def test_tag_auto_generates_slug(self):
        """Test that Tag automatically generates slug on save."""
        tag = Tag.objects.create(name="Test Tag")

        self.assertEqual(tag.slug, "test-tag")

    def test_tag_slug_for_chinese(self):
        """Test that Chinese names fallback to name for slug."""
        tag = Tag.objects.create(name="测试标签")

        self.assertEqual(tag.slug, "测试标签")

    def test_tag_unique_slug(self):
        """Test that tag slugs must be unique."""
        Tag.objects.create(name="tag-one", slug="unique-slug")

        with self.assertRaises(IntegrityError):
            Tag.objects.create(name="tag-two", slug="unique-slug")

    def test_tag_custom_slug(self):
        """Test creating tag with custom slug."""
        tag = Tag.objects.create(name="Custom Tag", slug="my-custom-slug")

        self.assertEqual(tag.slug, "my-custom-slug")

    def test_tag_is_default_field(self):
        """Test is_default field behavior."""
        default_tag = Tag.objects.create(name="default-tag", is_default=True)
        normal_tag = Tag.objects.create(name="normal-tag", is_default=False)

        self.assertTrue(default_tag.is_default)
        self.assertFalse(normal_tag.is_default)

    def test_tag_is_default_defaults_to_false(self):
        """Test that is_default defaults to False."""
        tag = Tag.objects.create(name="test-tag")

        self.assertFalse(tag.is_default)

    def test_tag_description_can_be_blank(self):
        """Test that description field can be blank."""
        tag = Tag.objects.create(name="no-description-tag")

        self.assertEqual(tag.description, "")

    def test_tag_description_can_be_set(self):
        """Test that description field can be set."""
        tag = Tag.objects.create(
            name="described-tag", description="这是一个测试标签的详细描述"
        )

        self.assertEqual(tag.description, "这是一个测试标签的详细描述")

    def test_tag_verbose_name(self):
        """Test Tag model verbose names."""
        self.assertEqual(Tag._meta.verbose_name, "积分标签")
        self.assertEqual(Tag._meta.verbose_name_plural, "积分标签")

    def test_tag_slug_blank_allowed(self):
        """Test that slug can be blank and will be auto-generated."""
        tag = Tag.objects.create(name="Auto Slug", slug="")

        self.assertEqual(tag.slug, "auto-slug")

    def test_tag_field_max_lengths(self):
        """Test field max length constraints."""
        # Test max_length for name
        long_name = "a" * 50
        tag = Tag.objects.create(name=long_name)
        self.assertEqual(len(tag.name), 50)

        # Test max_length for slug
        long_slug = "b" * 50
        tag2 = Tag.objects.create(name="test", slug=long_slug)
        self.assertEqual(len(tag2.slug), 50)

    def test_tag_withdrawable_field(self):
        """Test withdrawable field behavior."""
        withdrawable_tag = Tag.objects.create(
            name="withdrawable-tag", withdrawable=True
        )
        non_withdrawable_tag = Tag.objects.create(
            name="non-withdrawable-tag", withdrawable=False
        )

        self.assertTrue(withdrawable_tag.withdrawable)
        self.assertFalse(non_withdrawable_tag.withdrawable)

    def test_tag_withdrawable_defaults_to_false(self):
        """Test that withdrawable defaults to False."""
        tag = Tag.objects.create(name="test-tag")

        self.assertFalse(tag.withdrawable)


class PointSourceModelTests(TestCase):
    """Test cases for PointSource model."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password="password123"
        )
        self.tag = Tag.objects.create(name="test-tag")

    def test_point_source_creation(self):
        """Test creating a point source."""
        source = PointSource.objects.create(
            user_profile=self.user, initial_points=100, remaining_points=100
        )
        source.tags.add(self.tag)

        self.assertEqual(source.initial_points, 100)
        self.assertEqual(source.remaining_points, 100)
        self.assertEqual(source.tags.count(), 1)

    def test_point_source_ordering(self):
        """Test that point sources are ordered by created_at."""
        source1 = PointSource.objects.create(
            user_profile=self.user, initial_points=100, remaining_points=100
        )
        source2 = PointSource.objects.create(
            user_profile=self.user, initial_points=50, remaining_points=50
        )

        sources = PointSource.objects.all()

        self.assertEqual(sources[0], source1)
        self.assertEqual(sources[1], source2)

    def test_point_source_user_cascade_delete(self):
        """Test that point sources are deleted when user is deleted."""
        PointSource.objects.create(
            user_profile=self.user, initial_points=100, remaining_points=100
        )

        self.assertEqual(PointSource.objects.count(), 1)

        self.user.delete()

        self.assertEqual(PointSource.objects.count(), 0)

    def test_point_source_with_expiration(self):
        """Test creating point source with expiration date."""
        expires_at = timezone.now() + timezone.timedelta(days=30)
        source = PointSource.objects.create(
            user_profile=self.user,
            initial_points=100,
            remaining_points=100,
            expires_at=expires_at,
        )

        self.assertEqual(source.expires_at, expires_at)

    def test_point_source_without_expiration(self):
        """Test creating point source without expiration date."""
        source = PointSource.objects.create(
            user_profile=self.user, initial_points=100, remaining_points=100
        )

        self.assertIsNone(source.expires_at)

    def test_point_source_with_notes(self):
        """Test creating point source with notes."""
        notes = "这是签到奖励积分"
        source = PointSource.objects.create(
            user_profile=self.user,
            initial_points=100,
            remaining_points=100,
            notes=notes,
        )

        self.assertEqual(source.notes, notes)

    def test_point_source_notes_can_be_blank(self):
        """Test that notes field can be blank."""
        source = PointSource.objects.create(
            user_profile=self.user, initial_points=100, remaining_points=100
        )

        self.assertEqual(source.notes, "")

    def test_point_source_multiple_tags(self):
        """Test point source can have multiple tags."""
        tag1 = Tag.objects.create(name="tag1")
        tag2 = Tag.objects.create(name="tag2")
        tag3 = Tag.objects.create(name="tag3")

        source = PointSource.objects.create(
            user_profile=self.user, initial_points=100, remaining_points=100
        )
        source.tags.add(tag1, tag2, tag3)

        self.assertEqual(source.tags.count(), 3)
        self.assertIn(tag1, source.tags.all())
        self.assertIn(tag2, source.tags.all())
        self.assertIn(tag3, source.tags.all())

    def test_point_source_no_tags(self):
        """Test point source can exist without tags."""
        source = PointSource.objects.create(
            user_profile=self.user, initial_points=100, remaining_points=100
        )

        self.assertEqual(source.tags.count(), 0)

    def test_point_source_related_name_from_user(self):
        """Test accessing point sources from user via related name."""
        source1 = PointSource.objects.create(
            user_profile=self.user, initial_points=100, remaining_points=100
        )
        source2 = PointSource.objects.create(
            user_profile=self.user, initial_points=50, remaining_points=50
        )

        user_sources = self.user.point_sources.all()

        self.assertEqual(user_sources.count(), 2)
        self.assertIn(source1, user_sources)
        self.assertIn(source2, user_sources)

    def test_point_source_related_name_from_tag(self):
        """Test accessing point sources from tag via related name."""
        source1 = PointSource.objects.create(
            user_profile=self.user, initial_points=100, remaining_points=100
        )
        source1.tags.add(self.tag)

        source2 = PointSource.objects.create(
            user_profile=self.user, initial_points=50, remaining_points=50
        )
        source2.tags.add(self.tag)

        tag_sources = self.tag.point_sources.all()

        self.assertEqual(tag_sources.count(), 2)
        self.assertIn(source1, tag_sources)
        self.assertIn(source2, tag_sources)

    def test_point_source_verbose_name(self):
        """Test PointSource model verbose names."""
        self.assertEqual(PointSource._meta.verbose_name, "积分池")
        self.assertEqual(PointSource._meta.verbose_name_plural, "积分池")

    def test_point_source_created_at_auto_set(self):
        """Test that created_at is automatically set."""
        before = timezone.now()
        source = PointSource.objects.create(
            user_profile=self.user, initial_points=100, remaining_points=100
        )
        after = timezone.now()

        self.assertLessEqual(before, source.created_at)
        self.assertLessEqual(source.created_at, after)

    def test_point_source_created_at_indexed(self):
        """Test that created_at field has database index."""
        field = PointSource._meta.get_field("created_at")
        self.assertTrue(field.db_index)

    def test_point_source_expires_at_indexed(self):
        """Test that expires_at field has database index."""
        field = PointSource._meta.get_field("expires_at")
        self.assertTrue(field.db_index)

    def test_point_source_zero_points(self):
        """Test creating point source with zero points."""
        source = PointSource.objects.create(
            user_profile=self.user, initial_points=0, remaining_points=0
        )

        self.assertEqual(source.initial_points, 0)
        self.assertEqual(source.remaining_points, 0)

    def test_point_source_partially_consumed(self):
        """Test point source with different initial and remaining points."""
        source = PointSource.objects.create(
            user_profile=self.user, initial_points=100, remaining_points=30
        )

        self.assertEqual(source.initial_points, 100)
        self.assertEqual(source.remaining_points, 30)

    def test_point_source_user_profile_property_alias(self):
        """PointSource.user_profile setter mirrors legacy behavior."""
        source = PointSource(initial_points=10, remaining_points=10)

        source.user_profile = self.user

        self.assertEqual(source.user, self.user)
        self.assertIs(source.user_profile, self.user)

    def test_point_source_is_withdrawable_with_withdrawable_tag(self):
        """Test is_withdrawable property returns True when source has withdrawable tag."""
        withdrawable_tag = Tag.objects.create(
            name="withdrawable-tag", withdrawable=True
        )
        source = PointSource.objects.create(
            user_profile=self.user, initial_points=100, remaining_points=100
        )
        source.tags.add(withdrawable_tag)

        self.assertTrue(source.is_withdrawable)

    def test_point_source_is_withdrawable_without_withdrawable_tag(self):
        """Test is_withdrawable property returns False when source has no withdrawable tags."""
        non_withdrawable_tag = Tag.objects.create(
            name="non-withdrawable-tag", withdrawable=False
        )
        source = PointSource.objects.create(
            user_profile=self.user, initial_points=100, remaining_points=100
        )
        source.tags.add(non_withdrawable_tag)

        self.assertFalse(source.is_withdrawable)

    def test_point_source_is_withdrawable_with_mixed_tags(self):
        """Test is_withdrawable property returns True when at least one tag is withdrawable."""
        withdrawable_tag = Tag.objects.create(
            name="withdrawable-tag", withdrawable=True
        )
        non_withdrawable_tag = Tag.objects.create(
            name="non-withdrawable-tag", withdrawable=False
        )
        source = PointSource.objects.create(
            user_profile=self.user, initial_points=100, remaining_points=100
        )
        source.tags.add(withdrawable_tag, non_withdrawable_tag)

        self.assertTrue(source.is_withdrawable)

    def test_point_source_is_withdrawable_with_no_tags(self):
        """Test is_withdrawable property returns False when source has no tags."""
        source = PointSource.objects.create(
            user_profile=self.user, initial_points=100, remaining_points=100
        )

        self.assertFalse(source.is_withdrawable)


class PointTransactionModelTests(TestCase):
    """Test cases for PointTransaction model."""

    def setUp(self):
        """Set up test fixtures."""
        self.user = User.objects.create_user(
            username="testuser", email="test@example.com", password="password123"
        )

    def test_transaction_creation(self):
        """Test creating a transaction."""
        transaction = PointTransaction.objects.create(
            user_profile=self.user,
            points=100,
            transaction_type=PointTransaction.TransactionType.EARN,
            description="Test earn",
        )

        self.assertEqual(transaction.points, 100)
        self.assertEqual(transaction.transaction_type, "EARN")
        self.assertEqual(transaction.description, "Test earn")

    def test_transaction_ordering(self):
        """Test that transactions are ordered by created_at desc."""
        trans1 = PointTransaction.objects.create(
            user_profile=self.user,
            points=100,
            transaction_type=PointTransaction.TransactionType.EARN,
            description="First",
        )
        trans2 = PointTransaction.objects.create(
            user_profile=self.user,
            points=50,
            transaction_type=PointTransaction.TransactionType.EARN,
            description="Second",
        )

        transactions = PointTransaction.objects.all()

        self.assertEqual(transactions[0], trans2)
        self.assertEqual(transactions[1], trans1)

    def test_transaction_type_earn(self):
        """Test EARN transaction type."""
        transaction = PointTransaction.objects.create(
            user_profile=self.user,
            points=100,
            transaction_type=PointTransaction.TransactionType.EARN,
            description="签到奖励",
        )

        self.assertEqual(transaction.transaction_type, "EARN")
        self.assertTrue(
            transaction.get_transaction_type_display() == "获得"
        )  # Test verbose label

    def test_transaction_type_spend(self):
        """Test SPEND transaction type."""
        transaction = PointTransaction.objects.create(
            user_profile=self.user,
            points=-50,
            transaction_type=PointTransaction.TransactionType.SPEND,
            description="兑换商品",
        )

        self.assertEqual(transaction.transaction_type, "SPEND")
        self.assertTrue(
            transaction.get_transaction_type_display() == "消费"
        )  # Test verbose label

    def test_transaction_with_negative_points(self):
        """Test transaction can have negative points for spending."""
        transaction = PointTransaction.objects.create(
            user_profile=self.user,
            points=-100,
            transaction_type=PointTransaction.TransactionType.SPEND,
            description="消费积分",
        )

        self.assertEqual(transaction.points, -100)

    def test_transaction_with_positive_points(self):
        """Test transaction can have positive points for earning."""
        transaction = PointTransaction.objects.create(
            user_profile=self.user,
            points=100,
            transaction_type=PointTransaction.TransactionType.EARN,
            description="获得积分",
        )

        self.assertEqual(transaction.points, 100)

    def test_transaction_with_zero_points(self):
        """Test transaction can have zero points."""
        transaction = PointTransaction.objects.create(
            user_profile=self.user,
            points=0,
            transaction_type=PointTransaction.TransactionType.EARN,
            description="测试零积分",
        )

        self.assertEqual(transaction.points, 0)

    def test_transaction_user_cascade_delete(self):
        """Test that transactions are deleted when user is deleted."""
        PointTransaction.objects.create(
            user_profile=self.user,
            points=100,
            transaction_type=PointTransaction.TransactionType.EARN,
            description="Test",
        )

        self.assertEqual(PointTransaction.objects.count(), 1)

        self.user.delete()

        self.assertEqual(PointTransaction.objects.count(), 0)

    def test_transaction_user_profile_property_alias(self):
        """PointTransaction.user_profile setter mirrors legacy behavior."""
        transaction = PointTransaction(
            points=5, transaction_type=PointTransaction.TransactionType.EARN
        )

        transaction.user_profile = self.user

        self.assertEqual(transaction.user, self.user)
        self.assertIs(transaction.user_profile, self.user)


class PointQuerySetAliasTests(TestCase):
    """Ensure legacy queryset aliasing continues to work."""

    def setUp(self):
        """Create user and source fixtures for alias tests."""
        self.user = User.objects.create_user(
            username="alias-user", email="alias@example.com", password="password123"
        )
        self.source = PointSource.objects.create(
            user=self.user, initial_points=100, remaining_points=100
        )

    def test_filter_aliases_legacy_user_profile_lookup(self):
        """Filtering with user_profile prefix maps to the user field."""
        result = PointSource.objects.filter(user_profile__username="alias-user")

        self.assertIn(self.source, list(result))

    def test_get_aliases_legacy_user_profile_lookup(self):
        """get() accepts the legacy user_profile keyword."""
        fetched = PointSource.objects.get(user_profile=self.user)

        self.assertEqual(fetched, self.source)

    def test_filter_without_kwargs_triggers_no_alias_work(self):
        """Calling filter with no kwargs returns the same queryset."""
        qs = PointSource.objects.filter()

        self.assertEqual(qs.count(), 1)

    def test_alias_field_handles_empty_input(self):
        """_alias_field safely returns falsy input values."""
        qs = PointSource.objects.all()

        self.assertEqual(qs._alias_field(""), "")

    def test_order_by_alias_handles_prefixed_fields(self):
        """order_by converts prefixed legacy fields to current names."""
        other_user = User.objects.create_user(
            username="z-user", email="z@example.com", password="password123"
        )
        other_source = PointSource.objects.create(
            user=other_user, initial_points=50, remaining_points=50
        )

        ordered = list(
            PointSource.objects.order_by("-user_profile__username").values_list(
                "user__username", flat=True
            )
        )

        self.assertEqual(ordered, ["z-user", "alias-user"])

        other_source.delete()

    def test_values_aliases_legacy_user_profile_fields(self):
        """values() remaps legacy field and expression names."""
        rows = list(
            PointSource.objects.values(
                "user_profile__username",
                user_profile__username_label=F("user__username"),
            )
        )

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertIn("user__username", row)
        self.assertEqual(row["user__username"], "alias-user")
        self.assertIn("user__username_label", row)
        self.assertEqual(row["user__username_label"], "alias-user")

    def test_transaction_consumed_sources_relationship(self):
        """Test many-to-many relationship with consumed sources."""
        source1 = PointSource.objects.create(
            user_profile=self.user, initial_points=100, remaining_points=50
        )
        source2 = PointSource.objects.create(
            user_profile=self.user, initial_points=50, remaining_points=0
        )

        transaction = PointTransaction.objects.create(
            user_profile=self.user,
            points=-100,
            transaction_type=PointTransaction.TransactionType.SPEND,
            description="消费积分",
        )
        transaction.consumed_sources.add(source1, source2)

        self.assertEqual(transaction.consumed_sources.count(), 2)
        self.assertIn(source1, transaction.consumed_sources.all())
        self.assertIn(source2, transaction.consumed_sources.all())

    def test_transaction_no_consumed_sources(self):
        """Test transaction can exist without consumed sources (for EARN type)."""
        transaction = PointTransaction.objects.create(
            user_profile=self.user,
            points=100,
            transaction_type=PointTransaction.TransactionType.EARN,
            description="获得积分",
        )

        self.assertEqual(transaction.consumed_sources.count(), 0)

    def test_transaction_related_name_from_user(self):
        """Test accessing transactions from user via related name."""
        trans1 = PointTransaction.objects.create(
            user_profile=self.user,
            points=100,
            transaction_type=PointTransaction.TransactionType.EARN,
            description="First",
        )
        trans2 = PointTransaction.objects.create(
            user_profile=self.user,
            points=-50,
            transaction_type=PointTransaction.TransactionType.SPEND,
            description="Second",
        )

        user_transactions = self.user.point_transactions.all()

        self.assertEqual(user_transactions.count(), 2)
        # Note: ordering is descending by created_at
        self.assertIn(trans2, user_transactions)
        self.assertIn(trans1, user_transactions)

    def test_transaction_related_name_from_source(self):
        """Test accessing consuming transactions from source via related name."""
        source = PointSource.objects.create(
            user_profile=self.user, initial_points=100, remaining_points=50
        )

        trans1 = PointTransaction.objects.create(
            user_profile=self.user,
            points=-30,
            transaction_type=PointTransaction.TransactionType.SPEND,
            description="First spend",
        )
        trans1.consumed_sources.add(source)

        trans2 = PointTransaction.objects.create(
            user_profile=self.user,
            points=-20,
            transaction_type=PointTransaction.TransactionType.SPEND,
            description="Second spend",
        )
        trans2.consumed_sources.add(source)

        consuming_transactions = source.consuming_transactions.all()

        self.assertEqual(consuming_transactions.count(), 2)
        self.assertIn(trans1, consuming_transactions)
        self.assertIn(trans2, consuming_transactions)

    def test_transaction_verbose_name(self):
        """Test PointTransaction model verbose names."""
        self.assertEqual(PointTransaction._meta.verbose_name, "积分交易记录")
        self.assertEqual(PointTransaction._meta.verbose_name_plural, "积分交易记录")

    def test_transaction_created_at_auto_set(self):
        """Test that created_at is automatically set."""
        before = timezone.now()
        transaction = PointTransaction.objects.create(
            user_profile=self.user,
            points=100,
            transaction_type=PointTransaction.TransactionType.EARN,
            description="Test",
        )
        after = timezone.now()

        self.assertLessEqual(before, transaction.created_at)
        self.assertLessEqual(transaction.created_at, after)

    def test_transaction_created_at_indexed(self):
        """Test that created_at field has database index."""
        field = PointTransaction._meta.get_field("created_at")
        self.assertTrue(field.db_index)

    def test_transaction_description_max_length(self):
        """Test description field max length."""
        long_description = "a" * 255
        transaction = PointTransaction.objects.create(
            user_profile=self.user,
            points=100,
            transaction_type=PointTransaction.TransactionType.EARN,
            description=long_description,
        )

        self.assertEqual(len(transaction.description), 255)

    def test_transaction_type_choices(self):
        """Test that transaction type is limited to defined choices."""
        # Test valid choices
        earn_trans = PointTransaction.objects.create(
            user_profile=self.user,
            points=100,
            transaction_type="EARN",
            description="Earn test",
        )
        self.assertIn(earn_trans.transaction_type, ["EARN", "SPEND"])

        spend_trans = PointTransaction.objects.create(
            user_profile=self.user,
            points=-50,
            transaction_type="SPEND",
            description="Spend test",
        )
        self.assertIn(spend_trans.transaction_type, ["EARN", "SPEND"])

    def test_transaction_type_enum_values(self):
        """Test TransactionType enum has correct values."""
        self.assertEqual(PointTransaction.TransactionType.EARN, "EARN")
        self.assertEqual(PointTransaction.TransactionType.SPEND, "SPEND")

    def test_transaction_type_enum_labels(self):
        """Test TransactionType enum has correct labels."""
        self.assertEqual(PointTransaction.TransactionType.EARN.label, "获得")
        self.assertEqual(PointTransaction.TransactionType.SPEND.label, "消费")
