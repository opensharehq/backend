"""身边云签约用户本地落库模型."""

from django.db import models


class SignedUser(models.Model):
    """
    身边云签约用户记录 (funCode=6044 返回的单条数据).

    以 offset_id (sign_xxx) 作为业务唯一键; 同时用 (id_card, mobile, name)
    三元组作为增量同步时定位"上次同步到哪一条"的身份标记。
    """

    # 业务唯一键，来源 offsetId，形如 sign_2057189426369298434
    offset_id = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        verbose_name="签约 ID",
    )

    name = models.CharField(max_length=64, db_index=True, verbose_name="姓名")
    mobile = models.CharField(max_length=20, db_index=True, verbose_name="手机号")
    id_card = models.CharField(max_length=32, db_index=True, verbose_name="身份证号")

    provider_id = models.BigIntegerField(verbose_name="服务商 ID")
    payment_type = models.IntegerField(default=0, verbose_name="结算方式")
    state = models.IntegerField(default=1, db_index=True, verbose_name="签约状态")
    force_create_contract_flag = models.BooleanField(
        default=False, verbose_name="强制创建合同标记"
    )
    ret_msg = models.CharField(
        max_length=255, blank=True, default="", verbose_name="返回信息"
    )

    # 完整原始响应，便于后续字段扩展与排查
    raw_data = models.JSONField(default=dict, verbose_name="原始返回数据")

    created_at = models.DateTimeField(
        auto_now_add=True, db_index=True, verbose_name="入库时间"
    )
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        """Django ORM 元信息."""

        verbose_name = "身边云签约用户"
        verbose_name_plural = "身边云签约用户"
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["id_card", "mobile", "name"],
                name="sby_signed_identity_idx",
            ),
        ]

    def __str__(self) -> str:
        """返回人可读的签约用户描述."""
        return f"{self.name}({self.mobile}) [{self.offset_id}]"


class PaymentState(models.IntegerChoices):
    """身边云付款记录状态枚举."""

    INITIATED = 0, "已发起"
    PAYING = 1, "付款中"
    SUCCESS = 3, "成功"
    FAILED = 4, "失败"
    PENDING_CONFIRM = 6, "待用户确认"
    CANCELLED = 7, "已取消"


class PaymentRecord(models.Model):
    """提现付款状态记录表, 追踪每笔通过身边云发起的付款."""

    # 批次信息
    mer_batch_id = models.CharField(
        max_length=32, db_index=True, verbose_name="商户批次号"
    )
    mer_order_id = models.CharField(
        max_length=32, unique=True, verbose_name="商户订单号"
    )
    order_no = models.CharField(
        max_length=25, blank=True, default="", verbose_name="平台订单号"
    )

    # 关联提现申请
    withdrawal_request = models.ForeignKey(
        "points.WithdrawalRequest", on_delete=models.PROTECT, verbose_name="提现申请"
    )

    # 付款信息
    amount = models.PositiveIntegerField(verbose_name="付款金额（分）")
    fee = models.PositiveIntegerField(default=0, verbose_name="服务费（分）")
    user_fee = models.PositiveIntegerField(
        default=0, verbose_name="个人服务费/个税（分）"
    )
    user_due_amt = models.PositiveIntegerField(
        default=0, verbose_name="个人实际到账（分）"
    )

    # 状态
    state = models.IntegerField(
        choices=PaymentState.choices,
        default=PaymentState.INITIATED,
        verbose_name="付款状态",
    )
    res_msg = models.TextField(blank=True, default="", verbose_name="响应信息")

    # 收款人信息快照
    payee_name = models.CharField(max_length=50, verbose_name="收款人姓名")
    payee_acc = models.CharField(max_length=28, verbose_name="收款人账号")
    id_card = models.CharField(max_length=18, verbose_name="身份证号")
    mobile = models.CharField(max_length=11, verbose_name="手机号")
    payment_type = models.IntegerField(default=0, verbose_name="付款方式")

    # 时间
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")
    end_time = models.DateTimeField(null=True, blank=True, verbose_name="交易完成时间")

    class Meta:
        """Django ORM 元信息."""

        verbose_name = "付款记录"
        verbose_name_plural = "付款记录"
        indexes = [
            models.Index(fields=["mer_batch_id", "order_no"]),
            models.Index(fields=["state"]),
        ]

    def __str__(self):
        """返回人可读的付款记录描述."""
        return f"PaymentRecord({self.mer_order_id}, state={self.get_state_display()})"
