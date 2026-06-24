"""Data models for shop application."""

import uuid

from django.conf import settings
from django.db import models


def shop_item_card_path(instance, filename):
    """Generate upload path for shop item card image."""
    ext = filename.rsplit(".", 1)[-1].lower()
    return f"shop/items/{uuid.uuid4().hex}_card.{ext}"


def shop_item_detail_path(instance, filename):
    """Generate upload path for shop item detail image."""
    ext = filename.rsplit(".", 1)[-1].lower()
    return f"shop/items/{uuid.uuid4().hex}_detail.{ext}"


class ShopItem(models.Model):
    """商城商品模型."""

    name_zh = models.CharField(max_length=100, verbose_name="商品名称(中文)")
    name_en = models.CharField(max_length=100, verbose_name="商品名称(英文)")
    brief_zh = models.TextField(blank=True, default="", verbose_name="商品简介(中文)")
    brief_en = models.TextField(blank=True, default="", verbose_name="商品简介(英文)")
    description_zh = models.TextField(verbose_name="商品描述(中文)")
    description_en = models.TextField(
        blank=True, default="", verbose_name="商品描述(英文)"
    )

    # 图片双版本（UUID唯一文件名）
    image_card = models.FileField(
        upload_to=shop_item_card_path, null=True, blank=True, verbose_name="首页卡片图"
    )
    image_detail = models.FileField(
        upload_to=shop_item_detail_path,
        null=True,
        blank=True,
        verbose_name="详情页大图",
    )

    cost = models.PositiveIntegerField(verbose_name="所需积分")
    stock = models.PositiveIntegerField(
        null=True, blank=True, verbose_name="库存", help_text="留空表示无限库存"
    )
    is_active = models.BooleanField(default=True, verbose_name="是否上架")

    requires_shipping = models.BooleanField(
        default=False,
        verbose_name="需要线下发货",
        help_text="如果选中，用户兑换时需要提供收货地址",
    )

    # 积分标签限制
    allowed_tags = models.ManyToManyField(
        "points.Tag",
        blank=True,
        through="ShopItemAllowedTags",
        related_name="shop_items",
        verbose_name="允许的积分标签",
        help_text="如果为空，任何礼物积分都可兑换；否则只有指定标签的积分可用",
    )

    # 站内信模板（可选）
    message_title_template_zh = models.CharField(
        max_length=200, blank=True, default="", verbose_name="站内信标题模板(中文)"
    )
    message_title_template_en = models.CharField(
        max_length=200, blank=True, default="", verbose_name="站内信标题模板(英文)"
    )
    message_content_template_zh = models.TextField(
        blank=True, default="", verbose_name="站内信内容模板(中文)"
    )
    message_content_template_en = models.TextField(
        blank=True, default="", verbose_name="站内信内容模板(英文)"
    )

    # 兑换码类型关联（非实物商品可选）
    coupon_type = models.CharField(
        max_length=100, blank=True, default="", verbose_name="关联兑换码类型"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Model metadata."""

        verbose_name = "商城商品"
        verbose_name_plural = verbose_name

    def __str__(self):
        """Return string representation."""
        return self.name_zh

    def has_message_template(self):
        """Check if message template is configured."""
        return bool(
            self.message_title_template_zh
            or self.message_content_template_zh
            or self.message_title_template_en
            or self.message_content_template_en
        )


class ShopItemAllowedTags(models.Model):
    """Through table for shop items and allowed tags."""

    shopitem = models.ForeignKey(ShopItem, on_delete=models.CASCADE)
    tag = models.ForeignKey("points.Tag", on_delete=models.CASCADE)

    class Meta:
        """Model metadata."""

        db_table = "shop_shopitem_allowed_tags"
        unique_together = ("shopitem", "tag")


class Redemption(models.Model):
    """用户兑换记录."""

    class StatusChoices(models.TextChoices):
        """Status choices for redemption."""

        PENDING = "PENDING", "处理中"
        COMPLETED = "COMPLETED", "已完成"
        CANCELLED = "CANCELLED", "已取消"

    user_profile = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="redemptions"
    )
    item = models.ForeignKey(
        ShopItem,
        on_delete=models.PROTECT,  # 保护已兑换的商品信息不被删除
        related_name="redemptions",
    )
    points_cost_at_redemption = models.PositiveIntegerField(
        verbose_name="兑换时积分成本"
    )
    status = models.CharField(
        max_length=10, choices=StatusChoices.choices, default=StatusChoices.PENDING
    )
    shipping_address = models.ForeignKey(
        "accounts.ShippingAddress",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="redemptions",
        verbose_name="收货地址",
        help_text="兑换时用户选择的收货地址（仅需要线下发货的商品）",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        """Model metadata."""

        ordering = ["-created_at"]
        verbose_name = "兑换记录"
        verbose_name_plural = verbose_name

    def __str__(self):
        """Return string representation."""
        return f"{self.user_profile.username} redeemed {self.item.name_zh}"


class CouponCode(models.Model):
    """兑换码模型."""

    class Status(models.TextChoices):
        """Status choices for coupon code."""

        AVAILABLE = "available", "可用"
        USED = "used", "已使用"
        DISABLED = "disabled", "已禁用"

    code_type = models.CharField(
        max_length=100, db_index=True, verbose_name="兑换码类型"
    )
    code = models.CharField(max_length=500, verbose_name="兑换码")
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.AVAILABLE, db_index=True
    )
    redeemed_by = models.ForeignKey(
        "accounts.UserProfile",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        verbose_name="兑换用户",
    )
    redeemed_at = models.DateTimeField(null=True, blank=True, verbose_name="兑换时间")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        """Model metadata."""

        indexes = [
            models.Index(fields=["code_type", "status"]),
        ]
        unique_together = [("code_type", "code")]
        verbose_name = "兑换码"
        verbose_name_plural = "兑换码"

    def __str__(self):
        """Return string representation."""
        return f"{self.code_type}: {self.code[:20]}..."
