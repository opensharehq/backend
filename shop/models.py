"""Data models for shop application."""

from django.conf import settings
from django.db import models


class ShopItem(models.Model):
    """商城商品模型."""

    name = models.CharField(max_length=100, verbose_name="商品名称")
    description = models.TextField(verbose_name="商品描述")
    cost = models.PositiveIntegerField(verbose_name="所需积分")
    stock = models.PositiveIntegerField(
        null=True, blank=True, verbose_name="库存", help_text="留空表示无限库存"
    )
    is_active = models.BooleanField(default=True, verbose_name="是否上架")
    image = models.FileField(
        upload_to="shop/items/",
        null=True,
        blank=True,
        verbose_name="商品图片",
        help_text="商品展示图片",
    )

    requires_shipping = models.BooleanField(
        default=False,
        verbose_name="需要线下发货",
        help_text="如果选中，用户兑换时需要提供收货地址",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Model metadata."""

        verbose_name = "商城商品"
        verbose_name_plural = verbose_name

    def __str__(self):
        """Return string representation."""
        return f"{self.name} - {self.cost} pts"


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
        return f"{self.user_profile.username} redeemed {self.item.name}"
