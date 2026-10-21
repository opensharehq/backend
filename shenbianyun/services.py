"""身边云平台通用请求与响应处理服务."""

import base64
import json
import logging
import random
import secrets
import string
from datetime import datetime

import requests
from django.conf import settings

from .crypto import des_decrypt, des_encrypt, rsa_sign, rsa_verify

logger = logging.getLogger(__name__)

# 签约状态常量
SIGN_STATE_UNSIGNED = 0
SIGN_STATE_SIGNED = 1
SIGN_STATE_SIGNING = 3
SIGN_STATE_SIGN_FAILED = 4
SIGN_STATE_RELEASED = 5

# 签约时间起始默认值
_DEFAULT_CREATE_TIME_BEGIN = "1970-01-01 00:00:00"
_DATETIME_FMT = "%Y-%m-%d %H:%M:%S"

# 签约用户查询接口 funCode
FUN_CODE_SIGNED_USERS = "6044"

# 批量付款接口 funCode
FUN_CODE_BATCH_PAYMENT = "6001"

# 付款状态查询接口 funCode
FUN_CODE_PAYMENT_QUERY = "6002"

# 单批次最大付款条数
PAYMENT_BATCH_SIZE = 20

# 身边云 6044 接口单页最大返回条数（达到此值表明后面还有数据）
SIGNED_USERS_PAGE_SIZE = 50


class ShenbianyunError(Exception):
    """身边云平台对接基础异常."""


class ShenbianyunRequestError(ShenbianyunError):
    """网络/请求级别错误."""


class ShenbianyunSignatureError(ShenbianyunError):
    """签名/验签失败."""


class ShenbianyunResponseError(ShenbianyunError):
    """响应格式或校验不通过."""


def _generate_req_id(length: int = 30) -> str:
    """生成指定长度的随机请求序号 (字母+数字)."""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


class ShenbianyunClient:
    """身边云平台通用请求客户端."""

    def __init__(  # noqa: PLR0913
        self,
        api_url: str | None = None,
        mer_id: str | None = None,
        version: str | None = None,
        inter_key: str | None = None,
        mer_private_key: str | None = None,
        fu_public_key: str | None = None,
    ):
        """
        初始化客户端.

        所有参数可选, 未传入时从 Django settings 中读取。
        """
        self.api_url = api_url or settings.SBY_FU_URL
        self.mer_id = mer_id or settings.SBY_MER_ID
        self.version = version or settings.SBY_API_VERSION
        self.inter_key = inter_key or settings.SBY_INTER_KEY
        self.mer_private_key = mer_private_key or settings.SBY_MER_PRIVATE_KEY
        self.fu_public_key = fu_public_key or settings.SBY_FU_PUBLIC_KEY

    def request(self, fun_code: str, req_data: dict) -> dict:
        """
        发送请求到身边云平台并返回解析后的响应.

        Args:
            fun_code: 接口编码
            req_data: 业务数据字典

        Returns:
            {
                "res_code": str,
                "res_msg": str,
                "res_data": dict | None,
            }

        Raises:
            ShenbianyunRequestError: 请求发送失败
            ShenbianyunSignatureError: 响应验签失败
            ShenbianyunResponseError: 响应校验失败

        """
        req_id = _generate_req_id()

        # 1. 构造并加密 reqData
        req_data_json = json.dumps(req_data, ensure_ascii=False)
        req_data_bytes = req_data_json.encode("utf-8")

        # 2. DES 加密
        encrypted = des_encrypt(req_data_bytes, self.inter_key)

        # 3. Base64 编码
        req_data_b64 = base64.b64encode(encrypted).decode("utf-8")

        # 4. RSA 签名 (对 Base64 编码后的密文签名)
        sign = rsa_sign(req_data_b64.encode("utf-8"), self.mer_private_key)

        # 5. 组装请求参数
        payload = {
            "reqId": req_id,
            "funCode": fun_code,
            "merId": self.mer_id,
            "version": self.version,
            "reqData": req_data_b64,
            "sign": sign,
        }

        # 6. 发送请求
        logger.info(
            "身边云请求: funCode=%s, reqId=%s, url=%s",
            fun_code,
            req_id,
            self.api_url,
        )

        try:
            response = requests.post(
                self.api_url,
                json=payload,
                timeout=30,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            msg = f"身边云请求失败: {exc}"
            logger.error(msg)
            raise ShenbianyunRequestError(msg) from exc

        # 7. 解析响应
        try:
            resp_json = response.json()
        except (ValueError, json.JSONDecodeError) as exc:
            msg = f"身边云响应 JSON 解析失败: {response.text[:200]}"
            logger.error(msg)
            raise ShenbianyunResponseError(msg) from exc

        return self._process_response(resp_json, req_id, fun_code)

    def _process_response(self, resp_json: dict, req_id: str, fun_code: str) -> dict:
        """
        处理并校验响应数据.

        Args:
            resp_json: 原始响应 JSON
            req_id: 请求时的 reqId
            fun_code: 请求时的 funCode

        Returns:
            结构化的响应结果

        """
        res_code = resp_json.get("resCode", "")
        res_msg = resp_json.get("resMsg", "")
        res_data_b64 = resp_json.get("resData")
        resp_sign = resp_json.get("sign")

        result = {
            "res_code": res_code,
            "res_msg": res_msg,
            "res_data": None,
        }

        # 如果没有 resData，直接返回（某些错误响应可能不含 resData）
        if not res_data_b64:
            return result

        # 1. 验签：使用平台 RSA 公钥验证 sign 与 resData 的一致性
        if resp_sign:
            is_valid = rsa_verify(
                res_data_b64.encode("utf-8"),
                resp_sign,
                self.fu_public_key,
            )
            if not is_valid:
                msg = f"身边云响应验签失败: reqId={req_id}, funCode={fun_code}"
                logger.error(msg)
                raise ShenbianyunSignatureError(msg)
        else:
            msg = "身边云响应缺少签名字段"
            raise ShenbianyunSignatureError(msg)

        # 2. Base64 解码
        try:
            encrypted_bytes = base64.b64decode(res_data_b64)
        except Exception as exc:
            msg = f"身边云响应 resData Base64 解码失败: {exc}"
            raise ShenbianyunResponseError(msg) from exc

        # 3. DES 解密
        try:
            decrypted_bytes = des_decrypt(encrypted_bytes, self.inter_key)
        except Exception as exc:
            msg = f"身边云响应 resData 解密失败: {exc}"
            raise ShenbianyunResponseError(msg) from exc

        # 4. UTF-8 解码并解析 JSON
        try:
            decrypted_str = decrypted_bytes.decode("utf-8")
            res_data = json.loads(decrypted_str)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            msg = f"身边云响应 resData JSON 解析失败: {exc}"
            raise ShenbianyunResponseError(msg) from exc

        # 5. 校验公共字段一致性
        self._validate_response_fields(resp_json, req_id, fun_code)

        result["res_data"] = res_data
        return result

    def _validate_response_fields(
        self, resp_json: dict, req_id: str, fun_code: str
    ) -> None:
        """校验响应中的公共字段与请求时一致."""
        errors = []

        resp_req_id = resp_json.get("reqId", "")
        resp_fun_code = resp_json.get("funCode", "")
        resp_mer_id = resp_json.get("merId", "")
        resp_version = resp_json.get("version", "")

        if resp_req_id and resp_req_id != req_id:
            errors.append(f"reqId 不匹配: 期望={req_id}, 实际={resp_req_id}")

        if resp_fun_code and resp_fun_code != fun_code:
            errors.append(f"funCode 不匹配: 期望={fun_code}, 实际={resp_fun_code}")

        if resp_mer_id and resp_mer_id != self.mer_id:
            errors.append(f"merId 不匹配: 期望={self.mer_id}, 实际={resp_mer_id}")

        if resp_version and resp_version != self.version:
            errors.append(f"version 不匹配: 期望={self.version}, 实际={resp_version}")

        if errors:
            msg = "身边云响应校验失败: " + "; ".join(errors)
            logger.error(msg)
            raise ShenbianyunResponseError(msg)


def _generate_batch_id():
    """生成商户批次号: yyyymmddHHMM + 8位随机数字."""
    timestamp = datetime.now().strftime("%Y%m%d%H%M")
    random_part = "".join(random.choices(string.digits, k=8))  # noqa: S311
    return f"{timestamp}{random_part}"


def _generate_order_id():
    """生成商户订单号: yyyymmddHHMM + 8位随机数字."""
    timestamp = datetime.now().strftime("%Y%m%d%H%M")
    random_part = "".join(random.choices(string.digits, k=8))  # noqa: S311
    return f"{timestamp}{random_part}"


def _reserve_payments():
    """Claim withdrawals atomically; commit stable order IDs before external I/O."""
    from django.db import transaction

    from points.models import WithdrawalRefund, WithdrawalRequest, WithdrawalStatus
    from points.services import WithdrawalError, get_withdrawal_debits

    from .models import PaymentRecord

    candidates = (
        WithdrawalRequest.objects.filter(
            status=WithdrawalStatus.APPROVED,
        )
        .exclude(pk__in=PaymentRecord.objects.values("withdrawal_request_id"))
        .order_by("created_at", "pk")
        .values_list("pk", flat=True)[:PAYMENT_BATCH_SIZE]
    )
    batch_id = _generate_batch_id()
    records = []
    for pk in list(candidates):
        with transaction.atomic():
            withdrawal = WithdrawalRequest.objects.select_for_update().get(pk=pk)
            if (
                withdrawal.status != WithdrawalStatus.APPROVED
                or PaymentRecord.objects.filter(withdrawal_request=withdrawal).exists()
                or WithdrawalRefund.objects.filter(withdrawal=withdrawal).exists()
            ):
                continue
            try:
                get_withdrawal_debits(withdrawal)
            except WithdrawalError:
                logger.error("拒绝未足额扣款的提现付款: withdrawal_id=%s", pk)
                continue
            records.append(
                PaymentRecord.objects.create(
                    mer_batch_id=batch_id,
                    mer_order_id=f"osh-wd-{pk}",
                    withdrawal_request=withdrawal,
                    amount=withdrawal.amount * 10,
                    payee_name=withdrawal.real_name,
                    payee_acc=withdrawal.bank_account,
                    id_card=withdrawal.id_card,
                    mobile=withdrawal.phone,
                )
            )
    return records


def batch_payment():
    """Submit reserved orders once; ambiguous responses remain reconcilable."""
    from .models import PaymentRecord, PaymentState

    # Validate configuration before claiming any business orders.
    task_id, provider_id = int(settings.SBY_TASK_ID), int(settings.SBY_PROVIDER_ID)
    records = _reserve_payments()
    if not records:
        return {"batched": 0, "message": "无待付款的提现申请"}
    batch_id = records[0].mer_batch_id
    req_data = {
        "merBatchId": batch_id,
        "taskId": task_id,
        "providerId": provider_id,
        "payItems": [
            {
                "merOrderId": r.mer_order_id,
                "amt": r.amount,
                "payeeName": r.payee_name,
                "payeeAcc": r.payee_acc,
                "idCard": r.id_card,
                "mobile": r.mobile,
                "paymentType": r.payment_type,
                "memo": f"OpenShare {datetime.now().year}",
            }
            for r in records
        ],
    }
    record_map = {r.mer_order_id: r for r in records}
    try:
        response = ShenbianyunClient().request(
            fun_code=FUN_CODE_BATCH_PAYMENT,
            req_data=req_data,
        )
        results = (response.get("res_data") or {}).get("payResultList", [])
        updated = 0
        for result in results:
            record = record_map.get(result.get("merOrderId"))
            if not record:
                continue
            if result.get("amt", record.amount) != record.amount:
                msg = "付款响应金额与申请不一致"
                raise ShenbianyunResponseError(msg)
            # Never overwrite a terminal state written by a concurrent poll.
            updated += PaymentRecord.objects.filter(
                pk=record.pk,
                state__in=[PaymentState.INITIATED, PaymentState.UNKNOWN],
            ).update(
                order_no=str(result.get("orderNo") or ""),
                fee=result.get("fee") or 0,
                res_msg=result.get("resMsg") or "",
            )
        return {"batched": updated, "mer_batch_id": batch_id}
    except Exception:
        logger.exception("付款结果未知，保留扣款等待对账: mer_batch_id=%s", batch_id)
        PaymentRecord.objects.filter(
            pk__in=[r.pk for r in records],
            state=PaymentState.INITIATED,
        ).update(state=PaymentState.UNKNOWN, res_msg="请求结果未知，等待对账")
        return {
            "batched": 0,
            "error": "请求结果未知，等待对账",
            "mer_batch_id": batch_id,
        }


def _find_payment_record(batch_id, item):
    """Match only within the queried batch; empty platform IDs are not identities."""
    from .models import PaymentRecord

    records = PaymentRecord.objects.filter(mer_batch_id=batch_id)
    merchant_id = item.get("merOrderId")
    platform_id = str(item.get("orderNo") or "")
    if merchant_id:
        record = records.filter(mer_order_id=merchant_id).first()
        if (
            record
            and platform_id
            and record.order_no
            and record.order_no != platform_id
        ):
            return None
        return record
    if platform_id:
        matches = list(records.filter(order_no=platform_id)[:2])
        if len(matches) == 1:
            return matches[0]
    return None


def _settle_payment(record, item):
    """Serialize terminal transitions and their ledger effects with the withdrawal."""
    from django.db import transaction
    from django.utils import timezone

    from points.models import WithdrawalRefund, WithdrawalRequest, WithdrawalStatus
    from points.services import (
        WithdrawalError,
        get_withdrawal_debits,
        refund_withdrawal,
    )

    from .models import PaymentRecord, PaymentState

    try:
        state = int(item.get("state"))
    except (ValueError, TypeError):
        return False
    if state not in PaymentState.values or state == PaymentState.UNKNOWN:
        return False
    terminal = (PaymentState.SUCCESS, PaymentState.FAILED, PaymentState.CANCELLED)
    with transaction.atomic():
        withdrawal = WithdrawalRequest.objects.select_for_update().get(
            pk=record.withdrawal_request_id,
        )
        record = PaymentRecord.objects.select_for_update().get(pk=record.pk)
        if record.state in terminal:
            return False
        if (
            withdrawal.status != WithdrawalStatus.APPROVED
            or WithdrawalRefund.objects.filter(withdrawal=withdrawal).exists()
        ):
            logger.error("付款与提现状态冲突，需要人工对账: payment_id=%s", record.pk)
            return False
        get_withdrawal_debits(withdrawal)
        if item.get("amt", record.amount) != record.amount:
            msg = "付款查询金额与申请不一致"
            raise WithdrawalError(msg)
        record.state = state
        record.order_no = str(item.get("orderNo") or record.order_no)
        record.res_msg = item.get("resMsg") or ""
        record.fee = item.get("fee") or 0
        record.user_fee = item.get("userFee") or 0
        record.user_due_amt = item.get("userDueAmt") or 0
        if item.get("endTime"):
            try:
                record.end_time = timezone.make_aware(
                    datetime.strptime(item["endTime"], "%Y-%m-%d %H:%M:%S")
                )
            except (ValueError, TypeError):
                # Optional provider metadata must not block a verified settlement.
                # Keep any previously recorded time and log only our record ID.
                logger.warning(
                    "付款完成时间格式无效，保留原时间并继续结算: payment_id=%s",
                    record.pk,
                )
        if state == PaymentState.SUCCESS:
            withdrawal.status = WithdrawalStatus.COMPLETED
            withdrawal.processed_at = timezone.now()
            withdrawal.save(update_fields=["status", "processed_at", "updated_at"])
        elif state in (PaymentState.FAILED, PaymentState.CANCELLED):
            refund_withdrawal(withdrawal, reason=f"付款失败: {record.res_msg}")
        record.save()
        return state in terminal


def check_payment_status():
    """Keep querying unknown results; only definitive failures may refund points."""
    from .models import PaymentRecord, PaymentState

    pending = PaymentRecord.objects.filter(
        state__in=[
            PaymentState.INITIATED,
            PaymentState.UNKNOWN,
            PaymentState.PAYING,
            PaymentState.PENDING_CONFIRM,
        ]
    )
    batch_ids = list(pending.values_list("mer_batch_id", flat=True).distinct())
    if not batch_ids:
        return {"checked": 0, "message": "无待查询的付款记录"}
    total = 0
    for batch_id in batch_ids:
        try:
            response = ShenbianyunClient().request(
                fun_code=FUN_CODE_PAYMENT_QUERY,
                req_data={"merBatchId": batch_id},
            )
            items = (response.get("res_data") or {}).get("queryItems", [])
            if not isinstance(items, list):
                items = [items] if items else []
            for item in items:
                if not isinstance(item, dict):
                    continue
                record = _find_payment_record(batch_id, item)
                if record:
                    total += _settle_payment(record, item)
        except Exception:
            logger.exception(
                "付款查询/结算失败，保留状态等待对账: mer_batch_id=%s", batch_id
            )
    return {"checked": total}


def get_signed_users(  # noqa: PLR0913, PLR0912
    provider_id: int | str | None = None,
    create_time_begin: str = _DEFAULT_CREATE_TIME_BEGIN,
    create_time_end: str | None = None,
    state: int = SIGN_STATE_SIGNED,
    offset_id: str | None = None,
    client: ShenbianyunClient | None = None,
) -> list[dict]:
    """
    获取我的账号下的签约用户列表 (funCode=6044).

    Args:
        provider_id: 服务商 ID, 未传时从 settings.SBY_PROVIDER_ID 读取
        create_time_begin: 签约创建时间开始 (yyyy-MM-dd HH:mm:ss),
            默认 1970-01-01 00:00:00
        create_time_end: 签约创建时间结束 (yyyy-MM-dd HH:mm:ss),
            未传时使用当前时间
        state: 签约状态, 默认 1 (已签约)
        offset_id: 分页偏移量, 上一页末条记录的 offsetId
        client: 可选的 ShenbianyunClient 实例, 便于测试注入

    Returns:
        签约用户信息列表 (resData JSON 数组)。

    Raises:
        ShenbianyunError: 接口请求/验签/校验失败
        ValueError: provider_id 缺失或时间格式非法

    """
    if provider_id is None:
        provider_id = settings.SBY_PROVIDER_ID

    if provider_id in (None, ""):
        msg = "未配置服务商 ID (SBY_PROVIDER_ID)"
        raise ValueError(msg)

    try:
        provider_id_int = int(provider_id)
    except (TypeError, ValueError) as exc:
        msg = f"providerId 必须为数字: {provider_id!r}"
        raise ValueError(msg) from exc

    if create_time_end is None:
        create_time_end = datetime.now().strftime(_DATETIME_FMT)

    # 校验时间格式
    for label, value in (
        ("createTimeBegin", create_time_begin),
        ("createTimeEnd", create_time_end),
    ):
        try:
            datetime.strptime(value, _DATETIME_FMT)
        except ValueError as exc:
            msg = f"{label} 时间格式非法，需为 yyyy-MM-dd HH:mm:ss: {value!r}"
            raise ValueError(msg) from exc

    req_data = {
        "providerId": provider_id_int,
        "createTimeBegin": create_time_begin,
        "createTimeEnd": create_time_end,
        "state": int(state),
    }
    if offset_id:
        req_data["offsetId"] = offset_id

    if client is None:
        client = ShenbianyunClient()

    result = client.request(FUN_CODE_SIGNED_USERS, req_data)

    res_code = result.get("res_code")
    res_msg = result.get("res_msg")
    res_data = result.get("res_data")

    if res_code and res_code != "0000":
        msg = f"身边云签约用户查询失败: resCode={res_code}, resMsg={res_msg}"
        logger.error(msg)
        raise ShenbianyunResponseError(msg)

    if res_data is None:
        return []

    if isinstance(res_data, list):
        return res_data

    # 部分接口可能将数组包在对象内，做一次兼容
    if isinstance(res_data, dict):
        for key in ("list", "data", "records", "items"):
            value = res_data.get(key)
            if isinstance(value, list):
                return value

    msg = f"身边云签约用户响应格式非预期: {type(res_data).__name__}"
    logger.error(msg)
    raise ShenbianyunResponseError(msg)


def _record_identity(record: dict) -> tuple[str, str, str]:
    """提取记录的身份三元组 (id_card, mobile, name)."""
    return (
        str(record.get("idCard") or ""),
        str(record.get("mobile") or ""),
        str(record.get("name") or ""),
    )


def _upsert_signed_user(record: dict) -> tuple[bool, object]:
    """
    以 offset_id 为唯一键 upsert 一条记录.

    Returns:
        (created, instance)

    """
    # 避免顶层导入 models、避免 Django apps 未初始化问题
    from .models import SignedUser

    offset_id = record.get("offsetId")
    defaults = {
        "name": record.get("name") or "",
        "mobile": record.get("mobile") or "",
        "id_card": record.get("idCard") or "",
        "provider_id": record.get("providerId") or 0,
        "payment_type": record.get("paymentType") or 0,
        "state": record.get("state") if record.get("state") is not None else 1,
        "force_create_contract_flag": bool(
            record.get("forceCreateContractFlag") or False
        ),
        "ret_msg": (record.get("retMsg") or "")[:255],
        "raw_data": record,
    }
    obj, created = SignedUser.objects.update_or_create(
        offset_id=offset_id, defaults=defaults
    )
    return created, obj


def sync_signed_users(  # noqa: PLR0913, PLR0912, PLR0915
    provider_id: int | str | None = None,
    create_time_begin: str = _DEFAULT_CREATE_TIME_BEGIN,
    create_time_end: str | None = None,
    state: int = SIGN_STATE_SIGNED,
    client: ShenbianyunClient | None = None,
    max_pages: int = 1000,
) -> dict:
    """
    同步身边云签约用户到本地数据库.

    页逻辑 (平台返回为新->旧逆序):
      - 首次同步 (本地表为空): 一直翻页直到返回 < 50 条。
      - 增量同步 (本地已有数据):
        以本地最新一条记录的 (idCard, mobile, name) 三元组为分水岭,
        每页从前往后扫描, 遇到三元组完全同处停止, 之前的都是新增。

    Returns:
        {
            "pages": 拉取页数,
            "fetched": 总拉取条数,
            "created": 新增入库条数,
            "updated": 更新入库条数,
            "stopped_by": "identity_match" | "page_under_limit" | "max_pages",
        }

    """
    from .models import SignedUser

    # 定位本地最新一条作为增量分水岭
    # 按 offset_id 倍序：offsetId 格式为 sign_<19位雪花ID>，
    # 位数固定下字典序等价于数字序，代表业务最新。
    latest = SignedUser.objects.order_by("-offset_id").first()
    identity_marker: tuple[str, str, str] | None = None
    if latest is not None:
        identity_marker = (latest.id_card, latest.mobile, latest.name)
        logger.debug(
            "增量同步模式，分水岭: offset_id=%s",
            latest.offset_id,
        )
    else:
        logger.debug("首次全量同步模式")

    if client is None:
        client = ShenbianyunClient()

    pages = 0
    fetched_total = 0
    created_total = 0
    updated_total = 0
    offset_id: str | None = None
    stopped_by = "page_under_limit"

    while pages < max_pages:
        page = get_signed_users(
            provider_id=provider_id,
            create_time_begin=create_time_begin,
            create_time_end=create_time_end,
            state=state,
            offset_id=offset_id,
            client=client,
        )
        pages += 1
        fetched_total += len(page)
        logger.debug(
            "拉取第 %d 页，返回 %d 条",
            pages,
            len(page),
        )

        if not page:
            stopped_by = "page_under_limit"
            break

        # 增量模式: 从前往后扫描，遇到身份三元组匹配则其前面是新增
        match_index: int | None = None
        if identity_marker is not None:
            for idx, record in enumerate(page):
                if _record_identity(record) == identity_marker:
                    match_index = idx
                    break

        records_to_save = page if match_index is None else page[:match_index]

        for record in records_to_save:
            created, _ = _upsert_signed_user(record)
            if created:
                created_total += 1
            else:
                updated_total += 1

        if match_index is not None:
            stopped_by = "identity_match"
            logger.debug(
                "命中增量分水岭，本页新增 %d 条后停止",
                len(records_to_save),
            )
            break

        if len(page) < SIGNED_USERS_PAGE_SIZE:
            stopped_by = "page_under_limit"
            break

        # 下一页使用本页最后一条的 offsetId
        last_offset = page[-1].get("offsetId")
        if not last_offset:
            logger.warning("末条记录缺失 offsetId，提前终止翻页")
            stopped_by = "page_under_limit"
            break
        offset_id = last_offset
    else:
        stopped_by = "max_pages"
        logger.warning("达到 max_pages=%d 上限，提前终止", max_pages)

    return {
        "pages": pages,
        "fetched": fetched_total,
        "created": created_total,
        "updated": updated_total,
        "stopped_by": stopped_by,
    }
