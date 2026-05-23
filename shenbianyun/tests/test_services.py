"""Tests for the Shenbianyun request client."""

import base64
import json
from unittest import TestCase
from unittest.mock import MagicMock, patch

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


def _rsa_keypair():
    """Generate a test RSA key pair."""
    key = RSA.generate(1024)  # noqa: S505
    private_key_b64 = base64.b64encode(key.export_key("DER")).decode()
    public_key_b64 = base64.b64encode(key.publickey().export_key("DER")).decode()
    return private_key_b64, public_key_b64


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


class ShenbianyunClientTests(TestCase):
    """Tests for request assembly and response processing."""

    def setUp(self):
        """Create client keys for each test."""
        self.platform_private, fu_public = _rsa_keypair()
        mer_private, _ = _rsa_keypair()
        self.client = ShenbianyunClient(
            api_url=TEST_API_URL,
            mer_id=TEST_MER_ID,
            version=TEST_VERSION,
            inter_key=TEST_DES_KEY,
            mer_private_key=mer_private,
            fu_public_key=fu_public,
        )

    def test_generate_req_id_length(self):
        """Generated request IDs are 30 alphanumeric characters."""
        req_id = _generate_req_id()

        self.assertIsInstance(req_id, str)
        self.assertEqual(len(req_id), 30)
        self.assertTrue(req_id.isalnum())

    def test_generate_req_id_uniqueness(self):
        """Repeated request IDs are unique in a small sample."""
        ids = {_generate_req_id() for _ in range(100)}

        self.assertEqual(len(ids), 100)

    def test_request_success(self):
        """A valid encrypted and signed response is parsed successfully."""
        expected_res_data = {"orderId": "ORDER123", "amount": 100}
        captured = {}

        def fake_post(url, json=None, timeout=None):
            captured["url"] = url
            captured["payload"] = json
            captured["timeout"] = timeout

            req_id = json["reqId"]
            fun_code = json["funCode"]
            resp_json = _build_platform_response(
                expected_res_data, self.platform_private, req_id, fun_code
            )
            mock_resp = MagicMock()
            mock_resp.json.return_value = resp_json
            mock_resp.raise_for_status = MagicMock()
            return mock_resp

        with patch("shenbianyun.services.requests.post", side_effect=fake_post):
            result = self.client.request("FUN001", {"name": "test"})

        self.assertEqual(result["res_code"], "0000")
        self.assertEqual(result["res_msg"], "success")
        self.assertEqual(result["res_data"], expected_res_data)
        self.assertEqual(captured["url"], TEST_API_URL)
        self.assertEqual(captured["timeout"], 30)
        payload = captured["payload"]
        self.assertEqual(payload["funCode"], "FUN001")
        self.assertEqual(payload["merId"], TEST_MER_ID)
        self.assertEqual(payload["version"], TEST_VERSION)
        self.assertEqual(len(payload["reqId"]), 30)
        self.assertIn("reqData", payload)
        self.assertIn("sign", payload)

    def test_request_network_error(self):
        """Network errors are wrapped in ShenbianyunRequestError."""
        with patch(
            "shenbianyun.services.requests.post",
            side_effect=requests.ConnectionError("connection refused"),
        ):
            with self.assertRaises(ShenbianyunRequestError):
                self.client.request("FUN001", {"name": "test"})

    def test_request_invalid_json_response(self):
        """Non-JSON responses are wrapped in ShenbianyunResponseError."""
        mock_resp = MagicMock()
        mock_resp.json.side_effect = ValueError("not a JSON")
        mock_resp.text = "this is not json"
        mock_resp.raise_for_status = MagicMock()

        with patch("shenbianyun.services.requests.post", return_value=mock_resp):
            with self.assertRaises(ShenbianyunResponseError):
                self.client.request("FUN001", {"name": "test"})

    def test_request_signature_verification_failure(self):
        """Responses signed by an unrelated key are rejected."""
        wrong_private_b64, _ = _rsa_keypair()

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
            with self.assertRaises(ShenbianyunSignatureError):
                self.client.request("FUN001", {"name": "test"})

    def test_request_req_id_mismatch(self):
        """Mismatched response request IDs are rejected."""

        def fake_post(url, json=None, timeout=None):
            fun_code = json["funCode"]
            resp_json = _build_platform_response(
                {"orderId": "X"},
                self.platform_private,
                req_id="WRONG_REQ_ID_NOT_MATCHING_REQUEST",
                fun_code=fun_code,
            )
            mock_resp = MagicMock()
            mock_resp.json.return_value = resp_json
            mock_resp.raise_for_status = MagicMock()
            return mock_resp

        with patch("shenbianyun.services.requests.post", side_effect=fake_post):
            with self.assertRaises(ShenbianyunResponseError):
                self.client.request("FUN001", {"name": "test"})
