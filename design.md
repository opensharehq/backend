# 提现签署合同方案设计

## 提现要求

1. 用户提现时应该已经完成了提现合同签署；
2. 用户提现合同的签署需要提交姓名、身份证号、手机号、银行卡号。我们在合同签署时会传递这些参数过去；

## 交互步骤

1. 用户点击进入提现页面；
2. 用户选择要提现的积分；
3. 系统检测是否签署合同；
  3.1 如果已经签署完成，则直接发起提现申请；
  3.2 如果用户未完成签署，则让用户填写提现申请的表格，存储相关信息，并发起合同签署。发起合同签署后，提醒用户查收短信签署；

## 要开发的工作量

1. 改造当前的签署的工作流程；
2. 存储签署记录，并提供 Admin
3. 提供一个 Webhook，用于让法大大在签署完成后回调回来。


## 法大大参考代码

我已经写好了一个法大大的接入代码，请你参考这个封装一个 Client，提供自动算签名和请求 Access Token 的能力；此外，封装一个 signWithTemplate 的 method 占位。发起合同签署时调用这个函数，传入姓名、身份证号、手机号、银行卡号和存储的签署记录ID（方便实现回调。）

```python
import hashlib
import hmac
import json
import os
import secrets
import time

import requests

API_SUBVERSION = "5.1"
SIGN_TYPE = "HMAC-SHA256"
DEFAULT_TIMEOUT_SECONDS = 10

API_HOST = os.getenv("FDD_API_HOST", "https://uat-api.fadada.com/api/v5/")
APP_ID = os.getenv("FDD_APP_ID", "80004155")
APP_SECRET = os.getenv("FDD_APP_SECRET", "2T42FYODG7VQYQUMVZMWGNXQTORQKZYV")


def _now_millis() -> str:
    return str(int(time.time() * 1000))


def _nonce_32_digits() -> str:
    return f"{secrets.randbelow(10**32):032d}"


def generate_fdd_sign(app_secret: str, param_map: dict) -> str:
    """
    生成法大大 v5 API 的签名 (HMAC-SHA256)。

    规则（与官方 Java 伪代码一致）：
    1) 过滤空值参数；按 ASCII 升序排序；拼接成 k=v&k2=v2...
    2) signText = sha256Hex(paramToSignStr)
    3) secretSigning = hmacSha256(appSecret, timestamp)
    4) signature = hex(hmacSha256(secretSigning, signText)).toLowerCase()
    """
    filtered_params = {
        k: v for k, v in param_map.items()
        if v is not None and str(v).strip() != ""
    }
    # 按 ASCII 升序排序后拼接
    sorted_keys = sorted(filtered_params.keys())
    param_to_sign_str = "&".join([f"{k}={filtered_params[k]}" for k in sorted_keys])

    timestamp = str(filtered_params.get("X-FASC-Timestamp", "")).strip()
    if not timestamp:
        raise ValueError("X-FASC-Timestamp is required for signature generation")

    sign_text = hashlib.sha256(param_to_sign_str.encode("utf-8")).hexdigest()
    secret_signing = hmac.new(
        app_secret.encode("utf-8"),
        timestamp.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    signature = hmac.new(
        secret_signing,
        sign_text.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()

    return signature


def _build_signed_headers(
    *,
    app_id: str,
    app_secret: str,
    access_token: str | None = None,
    biz_content: str | None = None,
    extra_params: dict | None = None,
    api_subversion: str = API_SUBVERSION,
) -> dict[str, str]:
    timestamp = _now_millis()
    nonce = _nonce_32_digits()

    param_map: dict = {
        "X-FASC-App-Id": app_id,
        "X-FASC-Sign-Type": SIGN_TYPE,
        "X-FASC-Timestamp": timestamp,
        "X-FASC-Nonce": nonce,
        "X-FASC-Api-SubVersion": api_subversion,
    }
    if access_token:
        param_map["X-FASC-AccessToken"] = access_token
    if biz_content is not None:
        param_map["bizContent"] = biz_content
    if extra_params:
        param_map.update(extra_params)

    signature = generate_fdd_sign(app_secret, param_map)

    headers = {k: str(v) for k, v in param_map.items() if k != "bizContent"}
    headers["X-FASC-Sign"] = signature
    return headers


def get_fdd_access_token(api_host: str, app_id: str, app_secret: str) -> dict | None:
    """
    获取法大大 Access Token
    :param api_host: 环境域名, 例如 'https://openapi.fadada.com'
    :param app_id: 你的 AppId
    :param app_secret: 你的 AppSecret
    """
    url = f"{api_host.rstrip('/')}/service/get-access-token"

    # 获取 Token 时不需要 X-FASC-AccessToken / bizContent
    headers = _build_signed_headers(
        app_id=app_id,
        app_secret=app_secret,
        extra_params={"X-FASC-Grant-Type": "client_credential"},
    )

    try:
        # 发送 POST 请求 (虽然参数都在 header，但接口要求 POST)
        response = requests.post(url, headers=headers, timeout=DEFAULT_TIMEOUT_SECONDS)
        response.raise_for_status()  # 检查 HTTP 状态码

        result = response.json()
        return result
    except Exception as e:  # noqa: BLE001 - 示例脚本，保留统一异常提示
        print(f"请求异常: {e}")
        return None


def get_app_info(
    api_host: str,
    app_id: str,
    app_secret: str,
    access_token: str,
    queried_app_id: str | None = None,
) -> dict | None:
    """
    查询应用基本信息 (/app/get-info)
    :param api_host: 环境域名
    :param app_id: 你的 AppId
    :param app_secret: 你的 AppSecret
    :param access_token: 之前获取到的 AccessToken
    :param queried_app_id: (可选) 待查询的应用 AppId
    """
    url = f"{api_host.rstrip('/')}/app/get-info"

    # 1. 准备业务参数 (bizContent)
    # 逻辑：如果不传 queriedAppId，可以传空字典
    biz_data: dict = {}
    if queried_app_id:
        biz_data["queriedAppId"] = queried_app_id

    # 将业务参数转为紧凑的 JSON 字符串（无空格）
    biz_content = json.dumps(biz_data, separators=(',', ':'), ensure_ascii=False)

    # 2. 构建请求头 (签名时需要 bizContent，但 Header 中不包含 bizContent)
    headers = _build_signed_headers(
        app_id=app_id,
        app_secret=app_secret,
        access_token=access_token,
        biz_content=biz_content,
    )
    # 接口要求表单提交，否则会返回 Content-Type 不正确
    headers["Content-Type"] = "application/x-www-form-urlencoded"

    try:
        response = requests.post(
            url,
            data={"bizContent": biz_content},
            headers=headers,
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:  # noqa: BLE001 - 示例脚本，保留统一异常提示
        print(f"请求 [get-app-info] 异常: {e}")
        return None


def main():
    resp = get_fdd_access_token(API_HOST, APP_ID, APP_SECRET)
    if not resp:
        print("获取 Access Token 失败")
        return

    try:
        access_token = resp["data"]["accessToken"]
    except (KeyError, TypeError):
        print(f"Access Token 响应结构不符合预期: {resp}")
        return

    print(resp)
    print(access_token)

    resp2 = get_app_info(API_HOST, APP_ID, APP_SECRET, access_token, APP_ID)
    print(resp2)


if __name__ == "__main__":
    main()

```