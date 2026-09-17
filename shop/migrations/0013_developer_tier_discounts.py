from decimal import Decimal

import django.core.validators
from django.db import migrations, models


def create_default_discount_config(apps, schema_editor):
    """Create the singleton with the product-defined initial multipliers."""
    config_model = apps.get_model("shop", "DeveloperTierDiscountConfig")
    config_model.objects.update_or_create(
        pk=1,
        defaults={
            "sss_multiplier": Decimal("0.80"),
            "ss_multiplier": Decimal("0.85"),
            "s_multiplier": Decimal("0.90"),
            "a_multiplier": Decimal("0.95"),
            "b_multiplier": Decimal("0.95"),
        },
    )


class Migration(migrations.Migration):
    dependencies = [
        ("shop", "0012_shopitem_is_listed_on_cn_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="DeveloperTierDiscountConfig",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "sss_multiplier",
                    models.DecimalField(
                        decimal_places=2,
                        default=Decimal("0.80"),
                        help_text=(
                            "例如 0.80 表示按原积分的 80% 兑换，结果向上取整"
                        ),
                        max_digits=3,
                        validators=[
                            django.core.validators.MinValueValidator(Decimal("0.01")),
                            django.core.validators.MaxValueValidator(Decimal("1.00")),
                        ],
                        verbose_name="SSS 等级兑换倍率",
                    ),
                ),
                (
                    "ss_multiplier",
                    models.DecimalField(
                        decimal_places=2,
                        default=Decimal("0.85"),
                        max_digits=3,
                        validators=[
                            django.core.validators.MinValueValidator(Decimal("0.01")),
                            django.core.validators.MaxValueValidator(Decimal("1.00")),
                        ],
                        verbose_name="SS 等级兑换倍率",
                    ),
                ),
                (
                    "s_multiplier",
                    models.DecimalField(
                        decimal_places=2,
                        default=Decimal("0.90"),
                        max_digits=3,
                        validators=[
                            django.core.validators.MinValueValidator(Decimal("0.01")),
                            django.core.validators.MaxValueValidator(Decimal("1.00")),
                        ],
                        verbose_name="S 等级兑换倍率",
                    ),
                ),
                (
                    "a_multiplier",
                    models.DecimalField(
                        decimal_places=2,
                        default=Decimal("0.95"),
                        max_digits=3,
                        validators=[
                            django.core.validators.MinValueValidator(Decimal("0.01")),
                            django.core.validators.MaxValueValidator(Decimal("1.00")),
                        ],
                        verbose_name="A 等级兑换倍率",
                    ),
                ),
                (
                    "b_multiplier",
                    models.DecimalField(
                        decimal_places=2,
                        default=Decimal("0.95"),
                        max_digits=3,
                        validators=[
                            django.core.validators.MinValueValidator(Decimal("0.01")),
                            django.core.validators.MaxValueValidator(Decimal("1.00")),
                        ],
                        verbose_name="B 等级兑换倍率",
                    ),
                ),
                (
                    "updated_at",
                    models.DateTimeField(auto_now=True, verbose_name="更新时间"),
                ),
            ],
            options={
                "verbose_name": "开发者等级商城折扣",
                "verbose_name_plural": "开发者等级商城折扣",
            },
        ),
        migrations.AddField(
            model_name="redemption",
            name="discount_multiplier",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                max_digits=3,
                null=True,
                verbose_name="兑换时折扣倍率",
            ),
        ),
        migrations.AddField(
            model_name="redemption",
            name="discount_tier",
            field=models.CharField(
                blank=True,
                max_length=3,
                null=True,
                verbose_name="兑换时开发者等级",
            ),
        ),
        migrations.AddField(
            model_name="redemption",
            name="discount_tier_year",
            field=models.PositiveSmallIntegerField(
                blank=True,
                null=True,
                verbose_name="兑换时等级年份",
            ),
        ),
        migrations.AddField(
            model_name="redemption",
            name="original_points_cost_at_redemption",
            field=models.PositiveIntegerField(
                blank=True,
                help_text="折扣前的商品积分价格快照；历史记录可能为空",
                null=True,
                verbose_name="兑换时原始积分成本",
            ),
        ),
        migrations.RunPython(
            create_default_discount_config,
            migrations.RunPython.noop,
        ),
    ]
