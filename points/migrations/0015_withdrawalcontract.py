from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    """Create WithdrawalContract model for contract signing requirement."""

    dependencies = [
        ("points", "0014_create_default_tag"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="WithdrawalContract",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("status", models.CharField(choices=[("PENDING", "待签署"), ("SIGNED", "已签署"), ("REVOKED", "已作废")], db_index=True, default="PENDING", max_length=20, verbose_name="状态")),
                ("fadada_flow_id", models.CharField(max_length=128, unique=True, verbose_name="法大大流程ID")),
                ("sign_url", models.URLField(blank=True, max_length=500, verbose_name="签署链接")),
                ("signed_at", models.DateTimeField(blank=True, null=True, verbose_name="签署完成时间")),
                ("completion_source", models.CharField(blank=True, choices=[("CALLBACK", "法大大回调"), ("ADMIN", "管理员操作")], max_length=20, verbose_name="完成来源")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="创建时间")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="更新时间")),
                ("user", models.OneToOneField(on_delete=models.deletion.CASCADE, related_name="withdrawal_contract", to=settings.AUTH_USER_MODEL, verbose_name="用户")),
            ],
            options={
                "verbose_name": "提现合同",
                "verbose_name_plural": "提现合同",
            },
        ),
    ]
