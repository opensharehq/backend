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
            logger.warning(
                "身边云响应缺少签名字段: reqId=%s, funCode=%s",
                req_id,
                fun_code,
            )

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


def batch_payment():  # noqa: PLR0915
    """批量付款定时任务: 从已批准的提现申请中取20条, 调用 6001 接口."""
    from django.conf import settings
    from django.db import transaction

    from points.models import WithdrawalRequest, WithdrawalStatus

    from .models import PaymentRecord, PaymentState

    # 1. 获取已有PaymentRecord的提现申请ID，排除它们
    existing_wr_ids = PaymentRecord.objects.values_list(
        "withdrawal_request_id", flat=True
    )

    # 2. 查询最多20条已批准且未发起过付款的提现申请（按创建时间升序）
    withdrawals = (
        WithdrawalRequest.objects.filter(status=WithdrawalStatus.APPROVED)
        .exclude(id__in=existing_wr_ids)
        .select_related("withdrawal_account")
        .order_by("created_at")[:PAYMENT_BATCH_SIZE]
    )
    withdrawals = list(withdrawals)

    if not withdrawals:
        return {"batched": 0, "message": "无待付款的提现申请"}

    # 3. 生成批次号
    mer_batch_id = _generate_batch_id()

    # 4. 构造 payItems 并预创建 PaymentRecord (state=INITIATED, order_no 暂为空)
    #    预创建可保证：即使后续调用 6001 后本地崩溃，下次定时任务也不会因为提现
    #    无 PaymentRecord 而被重复付款。
    pay_items = []
    order_id_map = {}  # mer_order_id -> withdrawal
    record_map = {}  # mer_order_id -> PaymentRecord

    for wr in withdrawals:
        mer_order_id = _generate_order_id()
        order_id_map[mer_order_id] = wr

        # 收款人信息优先从 WithdrawalAccount 获取
        if wr.withdrawal_account:
            payee_name = wr.withdrawal_account.real_name
            payee_acc = wr.withdrawal_account.bank_card
            id_card = wr.withdrawal_account.id_card
            mobile = wr.withdrawal_account.phone
        else:
            payee_name = wr.real_name
            payee_acc = wr.bank_account
            id_card = wr.id_card
            mobile = wr.phone

        amt = wr.amount * 10  # 积分值 * 10 = 分

        pay_items.append(
            {
                "merOrderId": mer_order_id,
                "amt": amt,
                "payeeName": payee_name,
                "payeeAcc": payee_acc,
                "idCard": id_card,
                "mobile": mobile,
                "paymentType": 0,  # 银行卡
            }
        )

        record = PaymentRecord.objects.create(
            mer_batch_id=mer_batch_id,
            mer_order_id=mer_order_id,
            order_no="",
            withdrawal_request=wr,
            amount=amt,
            fee=0,
            state=PaymentState.INITIATED,
            res_msg="",
            payee_name=payee_name,
            payee_acc=payee_acc,
            id_card=id_card,
            mobile=mobile,
            payment_type=0,
        )
        record_map[mer_order_id] = record

    # 5. 构造请求数据
    req_data = {
        "merBatchId": mer_batch_id,
        "payItems": pay_items,
        "taskId": int(settings.SBY_TASK_ID),
        "providerId": int(settings.SBY_PROVIDER_ID),
    }

    # 6. 发送请求
    client = ShenbianyunClient()
    try:
        res_data = client.request(fun_code=FUN_CODE_BATCH_PAYMENT, req_data=req_data)
    except Exception:
        logger.exception("批量付款请求失败, mer_batch_id=%s", mer_batch_id)
        # 整体请求失败：将这批预创建的 PaymentRecord 标记为 FAILED，
        # 并将对应的 WithdrawalRequest 标记为 rejected。
        for mer_order_id, record in record_map.items():
            wr = order_id_map[mer_order_id]
            with transaction.atomic():
                record.state = PaymentState.FAILED
                record.res_msg = "请求失败"
                record.save(update_fields=["state", "res_msg", "updated_at"])
                wr.status = WithdrawalStatus.REJECTED
                wr.admin_note = "付款失败: 请求失败"
                wr.save(update_fields=["status", "admin_note", "updated_at"])
        return {"batched": 0, "error": "请求失败"}

    # 7. 解析响应，更新预创建的 PaymentRecord
    res_data_inner = res_data.get("res_data") or {}
    pay_result_list = res_data_inner.get("payResultList", [])
    updated_count = 0

    for result in pay_result_list:
        mer_order_id = result.get("merOrderId", "")
        record = record_map.get(mer_order_id)
        if not record:
            continue

        # 找到对应的 pay_item 获取兜底金额
        pay_item = next((p for p in pay_items if p["merOrderId"] == mer_order_id), None)
        if not pay_item:
            continue

        record.order_no = str(result.get("orderNo", ""))
        record.amount = result.get("amt", pay_item["amt"])
        record.fee = result.get("fee", 0) or 0
        record.res_msg = result.get("resMsg", "") or ""
        record.save(
            update_fields=["order_no", "amount", "fee", "res_msg", "updated_at"]
        )
        updated_count += 1

    logger.info(
        "批量付款完成: mer_batch_id=%s, 提交=%d, 受理=%d",
        mer_batch_id,
        len(withdrawals),
        updated_count,
    )
    return {"batched": updated_count, "mer_batch_id": mer_batch_id}


def check_payment_status():  # noqa: PLR0915, PLR0912
    """定时查询付款结果: 查询所有未完成的 PaymentRecord 状态."""
    from django.db import transaction
    from django.utils import timezone

    from points.models import WithdrawalStatus

    from .models import PaymentRecord, PaymentState

    # 1. 查询未完成的记录（PENDING_CONFIRM 也纳入轮询，作为防御性兜底）
    pending_records = PaymentRecord.objects.filter(
        state__in=[
            PaymentState.INITIATED,
            PaymentState.PAYING,
            PaymentState.PENDING_CONFIRM,
        ]
    )

    if not pending_records.exists():
        return {"checked": 0, "message": "无待查询的付款记录"}

    # 2. 去重获取批次号
    batch_ids = list(pending_records.values_list("mer_batch_id", flat=True).distinct())

    client = ShenbianyunClient()
    total_updated = 0

    # 3. 逐批次查询
    for mer_batch_id in batch_ids:
        try:
            res_data = client.request(
                fun_code=FUN_CODE_PAYMENT_QUERY,
                req_data={"merBatchId": mer_batch_id},
            )
        except Exception:
            logger.exception("付款状态查询失败, mer_batch_id=%s", mer_batch_id)
            continue

        # 4. 解析 queryItems
        res_data_inner = res_data.get("res_data") or {}
        query_items = res_data_inner.get("queryItems", [])
        if not isinstance(query_items, list):
            query_items = [query_items] if query_items else []

        for item in query_items:
            order_no = str(item.get("orderNo", ""))
            state = item.get("state")
            if state is None:
                continue

            state = int(state)

            # 通过 mer_batch_id + order_no 定位记录
            try:
                record = PaymentRecord.objects.get(
                    mer_batch_id=mer_batch_id, order_no=order_no
                )
            except PaymentRecord.DoesNotExist:
                # 也尝试通过 merOrderId 匹配
                mer_order_id = item.get("merOrderId", "")
                try:
                    record = PaymentRecord.objects.get(mer_order_id=mer_order_id)
                except PaymentRecord.DoesNotExist:
                    logger.warning(
                        "未找到付款记录: mer_batch_id=%s, order_no=%s",
                        mer_batch_id,
                        order_no,
                    )
                    continue
                # 回写 order_no 便于后续按平台订单号检索
                if order_no and not record.order_no:
                    record.order_no = order_no

            # 5. 更新 PaymentRecord 状态和详细信息
            record.state = state
            record.res_msg = item.get("resMsg", "") or ""
            record.fee = item.get("fee", 0) or 0
            record.user_fee = item.get("userFee", 0) or 0
            record.user_due_amt = item.get("userDueAmt", 0) or 0

            end_time_str = item.get("endTime")
            if end_time_str:
                try:
                    record.end_time = timezone.datetime.strptime(
                        end_time_str, "%Y-%m-%d %H:%M:%S"
                    )
                except (ValueError, TypeError):
                    pass

            # 6. 终态时同步更新提现申请，事务保护避免出现 PaymentRecord
            #    与 WithdrawalRequest 状态不一致的中间态。
            wr = record.withdrawal_request
            if state == PaymentState.SUCCESS:
                with transaction.atomic():
                    record.save()
                    wr.status = WithdrawalStatus.COMPLETED
                    wr.processed_at = timezone.now()
                    wr.save(update_fields=["status", "processed_at", "updated_at"])
                total_updated += 1
            elif state in (PaymentState.FAILED, PaymentState.CANCELLED):
                with transaction.atomic():
                    record.save()
                    wr.status = WithdrawalStatus.REJECTED
                    wr.admin_note = (
                        f"付款失败: {record.res_msg}" if record.res_msg else "付款失败"
                    )
                    wr.save(update_fields=["status", "admin_note", "updated_at"])
                total_updated += 1
            else:
                # 非终态 (PAYING / PENDING_CONFIRM) 仅保存状态变更
                record.save()

    logger.info(
        "付款状态查询完成: 批次数=%d, 状态更新=%d", len(batch_ids), total_updated
    )
    return {"checked": len(batch_ids), "updated": total_updated}


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
