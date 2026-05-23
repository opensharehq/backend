"""身边云加解密工具单元测试."""

import base64

import pytest
from Crypto.PublicKey import RSA

from shenbianyun.crypto import des_decrypt, des_encrypt, rsa_sign, rsa_verify

# 测试用 DES 密钥 (身边云只取前 8 个字符为 DES key)
TEST_DES_KEY = "0123456789ABCDEFFEDCBA9876543210"


@pytest.fixture
def rsa_keypair():
    """生成测试用 RSA 密钥对."""
    key = RSA.generate(1024)  # noqa: S505
    private_key_b64 = base64.b64encode(key.export_key("DER")).decode()
    public_key_b64 = base64.b64encode(key.publickey().export_key("DER")).decode()
    return private_key_b64, public_key_b64


@pytest.fixture
def another_rsa_keypair():
    """生成另一对 RSA 密钥用于错误密钥测试."""
    key = RSA.generate(1024)  # noqa: S505
    private_key_b64 = base64.b64encode(key.export_key("DER")).decode()
    public_key_b64 = base64.b64encode(key.publickey().export_key("DER")).decode()
    return private_key_b64, public_key_b64


def test_des_encrypt_decrypt_roundtrip():
    """加密后解密应得到原文."""
    plaintext = "你好，身边云！Hello, world!".encode()
    ciphertext = des_encrypt(plaintext, TEST_DES_KEY)
    decrypted = des_decrypt(ciphertext, TEST_DES_KEY)
    assert decrypted == plaintext


def test_des_encrypt_produces_different_output():
    """密文与明文不同."""
    plaintext = b"sensitive_data_payload_1234567890"
    ciphertext = des_encrypt(plaintext, TEST_DES_KEY)
    assert ciphertext != plaintext
    # 密文长度应为 block_size 的倍数
    assert len(ciphertext) % 8 == 0


def test_des_decrypt_invalid_data():
    """解密无效数据应抛出异常."""
    invalid_ciphertext = b"not-a-valid-des-ciphertext-block"
    with pytest.raises(Exception):  # noqa: B017
        des_decrypt(invalid_ciphertext, TEST_DES_KEY)


def test_rsa_sign_verify_roundtrip(rsa_keypair):
    """签名后验签应通过."""
    private_key_b64, public_key_b64 = rsa_keypair
    data = b"data-to-be-signed-12345"
    signature = rsa_sign(data, private_key_b64)
    assert isinstance(signature, str)
    assert len(signature) > 0
    assert rsa_verify(data, signature, public_key_b64) is True


def test_rsa_verify_tampered_data(rsa_keypair):
    """篡改数据后验签应失败."""
    private_key_b64, public_key_b64 = rsa_keypair
    data = b"original-data-payload"
    signature = rsa_sign(data, private_key_b64)

    tampered = b"tampered-data-payload"
    assert rsa_verify(tampered, signature, public_key_b64) is False


def test_rsa_verify_wrong_key(rsa_keypair, another_rsa_keypair):
    """使用错误公钥验签应失败."""
    private_key_b64, _ = rsa_keypair
    _, wrong_public_key_b64 = another_rsa_keypair

    data = b"data-signed-by-keypair-1"
    signature = rsa_sign(data, private_key_b64)

    assert rsa_verify(data, signature, wrong_public_key_b64) is False
