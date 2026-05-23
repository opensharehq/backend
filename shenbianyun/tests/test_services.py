"""身边云通用请求服务单元测试."""

import base64
import json
from unittest.mock import MagicMock, patch

import pytest
import requests
from Crypto.PublicKey import RSA

from shenbianyun.crypto import des_encrypt, rsa_sign
from shenbianyun.services import (
    ShenbianyunClient,
    ShenbianyunRequestError,
    ShenbianyunResponseError,
    ShenbianyunSignatureError,
    _generate_req_id,
)

TEST_DES_KEY = "0123456789ABCDEFFEDCBA9876543210"
TEST_API_URL = "http://test.example.com/api"
TEST_MER_ID = "TEST_MER_001"
TEST_VERSION = "V1.0"


@pytest.fixture
def platform_keypair():
    """模拟平台侧 RSA 密钥对（用于平台签名响应）."""
    key = RSA.generate(1024)  # noqa: S505
    private_key_b64 = base64.b64encode(key.export_key("DER")).decode()
    public_key_b64 = base64.b64encode(key.publickey().export_key("DER")).decode()
    return private_key_b64, public_key_b64


@pytest.fixture
def merchant_keypair():
    """商户侧 RSA 密钥对（用于商户签名请求）."""
    key = RSA.generate(1024)  # noqa: S505
    private_key_b64 = base64.b64encode(key.export_key("DER")).decode()
    public_key_b64 = base64.b64encode(key.publickey().export_key("DER")).decode()
    return private_key_b64, public_key_b64


@pytest.fixture
def client(merchant_keypair, platform_keypair):
    """创建测试用客户端实例."""
    mer_private, _ = merchant_keypair
    _, fu_public = platform_keypair
    return ShenbianyunClient(
        api_url=TEST_API_URL,
        mer_id=TEST_MER_ID,
        version=TEST_VERSION,
        inter_key=TEST_DES_KEY,
        mer_private_key=mer_private,
        fu_public_key=fu_public,
    )


def _build_platform_response(  # noqa: PLR0913
    res_data: dict,
    platform_private_key_b64: str,
    req_id: str,
    fun_code: str,
    mer_id: str = TEST_MER_ID,
    version: str = TEST_VERSION,
    res_code: str = "0000",
    res_msg: str = "success",
) -> dict:
    """模拟平台侧使用 DES 加密 + RSA 签名构造响应数据."""
    res_data_json = json.dumps(res_data, ensure_ascii=False).encode("utf-8")
    encrypted = des_encrypt(res_data_json, TEST_DES_KEY)
    res_data_b64 = base64.b64encode(encrypted).decode("utf-8")
    sign = rsa_sign(res_data_b64.encode("utf-8"), platform_private_key_b64)

    return {
        "reqId": req_id,
        "funCode": fun_code,
        "merId": mer_id,
        "version": version,
        "resCode": res_code,
        "resMsg": res_msg,
        "resData": res_data_b64,
        "sign": sign,
    }


def test_generate_req_id_length():
    """验证 _generate_req_id 生成 30 位字符串."""
    req_id = _generate_req_id()
    assert isinstance(req_id, str)
    assert len(req_id) == 30
    assert req_id.isalnum()


def test_generate_req_id_uniqueness():
    """多次调用生成的值不同."""
    ids = {_generate_req_id() for _ in range(100)}
    assert len(ids) == 100


def test_request_success(client, platform_keypair):
    """mock requests.post 返回正确加密签名的响应，验证完整流程."""
    platform_private, _ = platform_keypair
    expected_res_data = {"orderId": "ORDER123", "amount": 100}

    captured = {}

    def fake_post(url, json=None, timeout=None):
        # 记录请求信息以校验请求组装正确性
        captured["url"] = url
        captured["payload"] = json
        captured["timeout"] = timeout

        req_id = json["reqId"]
        fun_code = json["funCode"]

        resp_json = _build_platform_response(
            expected_res_data, platform_private, req_id, fun_code
        )
        mock_resp = MagicMock()
        mock_resp.json.return_value = resp_json
        mock_resp.raise_for_status = MagicMock()
        return mock_resp

    with patch("shenbianyun.services.requests.post", side_effect=fake_post):
        result = client.request("FUN001", {"name": "test"})

    # 校验响应解析结果
    assert result["res_code"] == "0000"
    assert result["res_msg"] == "success"
    assert result["res_data"] == expected_res_data

    # 校验请求组装
    assert captured["url"] == TEST_API_URL
    assert captured["timeout"] == 30
    payload = captured["payload"]
    assert payload["funCode"] == "FUN001"
    assert payload["merId"] == TEST_MER_ID
    assert payload["version"] == TEST_VERSION
    assert len(payload["reqId"]) == 30
    assert "reqData" in payload
    assert "sign" in payload


def test_request_network_error(client):
    """mock requests.post 抛出 ConnectionError，验证抛出 ShenbianyunRequestError."""
    with patch(
        "shenbianyun.services.requests.post",
        side_effect=requests.ConnectionError("connection refused"),
    ):
        with pytest.raises(ShenbianyunRequestError):
            client.request("FUN001", {"name": "test"})


def test_request_invalid_json_response(client):
    """mock 返回非 JSON 响应，验证抛出 ShenbianyunResponseError."""
    mock_resp = MagicMock()
    mock_resp.json.side_effect = ValueError("not a JSON")
    mock_resp.text = "this is not json"
    mock_resp.raise_for_status = MagicMock()

    with patch("shenbianyun.services.requests.post", return_value=mock_resp):
        with pytest.raises(ShenbianyunResponseError):
            client.request("FUN001", {"name": "test"})


def test_request_signature_verification_failure(client, platform_keypair):
    """mock 返回签名不匹配的响应，验证抛出 ShenbianyunSignatureError."""
    # 使用另一对完全不同的 RSA 私钥来签名，使其与 client 持有的平台公钥不匹配
    wrong_key = RSA.generate(1024)  # noqa: S505
    wrong_private_b64 = base64.b64encode(wrong_key.export_key("DER")).decode()

    def fake_post(url, json=None, timeout=None):
        req_id = json["reqId"]
        fun_code = json["funCode"]
        resp_json = _build_platform_response(
            {"orderId": "X"}, wrong_private_b64, req_id, fun_code
        )
        mock_resp = MagicMock()
        mock_resp.json.return_value = resp_json
        mock_resp.raise_for_status = MagicMock()
        return mock_resp

    with patch("shenbianyun.services.requests.post", side_effect=fake_post):
        with pytest.raises(ShenbianyunSignatureError):
            client.request("FUN001", {"name": "test"})


def test_request_req_id_mismatch(client, platform_keypair):
    """mock 返回 reqId 不一致的响应，验证抛出 ShenbianyunResponseError."""
    platform_private, _ = platform_keypair

    def fake_post(url, json=None, timeout=None):
        fun_code = json["funCode"]
        # 故意使用错误的 req_id 来构造响应
        resp_json = _build_platform_response(
            {"orderId": "X"},
            platform_private,
            req_id="WRONG_REQ_ID_NOT_MATCHING_REQUEST",
            fun_code=fun_code,
        )
        mock_resp = MagicMock()
        mock_resp.json.return_value = resp_json
        mock_resp.raise_for_status = MagicMock()
        return mock_resp

    with patch("shenbianyun.services.requests.post", side_effect=fake_post):
        with pytest.raises(ShenbianyunResponseError):
            client.request("FUN001", {"name": "test"})
