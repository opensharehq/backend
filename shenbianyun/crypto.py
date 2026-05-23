"""身边云平台加解密与签名/验签工具."""

import base64

from Crypto.Cipher import DES
from Crypto.Hash import SHA1
from Crypto.PublicKey import RSA
from Crypto.Signature import pkcs1_15
from Crypto.Util.Padding import pad, unpad


def des_encrypt(plaintext: bytes, key: str) -> bytes:
    """
    使用 DES-ECB 模式加密明文 (与身边云官方示例一致).

    Args:
        plaintext: 待加密的明文字节数组
        key: INTER_KEY 字符串, 仅取前 8 个字符作为 UTF-8 字节作为 DES 密钥

    Returns:
        加密后的密文字节数组 (PKCS7 填充)

    """
    key_bytes = key[:8].encode("utf-8")
    cipher = DES.new(key_bytes, DES.MODE_ECB)  # noqa: S304
    padded = pad(plaintext, DES.block_size, style="pkcs7")
    return cipher.encrypt(padded)


def des_decrypt(ciphertext: bytes, key: str) -> bytes:
    """
    使用 DES-ECB 模式解密密文 (与身边云官方示例一致).

    Args:
        ciphertext: 待解密的密文字节数组
        key: INTER_KEY 字符串, 仅取前 8 个字符作为 UTF-8 字节作为 DES 密钥

    Returns:
        解密后的明文字节数组

    """
    key_bytes = key[:8].encode("utf-8")
    cipher = DES.new(key_bytes, DES.MODE_ECB)  # noqa: S304
    decrypted = cipher.decrypt(ciphertext)
    return unpad(decrypted, DES.block_size, style="pkcs7")


def rsa_sign(data: bytes, private_key_b64: str) -> str:
    """
    使用 RSA 私钥对数据进行 SHA1withRSA 签名.

    Args:
        data: 待签名的数据字节数组
        private_key_b64: Base64 编码的 RSA 私钥 (无 PEM 头尾)

    Returns:
        Base64 编码的签名结果字符串

    """
    pem_key = _wrap_pem(private_key_b64, "RSA PRIVATE KEY")
    rsa_key = RSA.import_key(pem_key)

    hash_obj = SHA1.new(data)
    signature = pkcs1_15.new(rsa_key).sign(hash_obj)
    return base64.b64encode(signature).decode("utf-8")


def rsa_verify(data: bytes, signature_b64: str, public_key_b64: str) -> bool:
    """
    使用 RSA 公钥验证 SHA1withRSA 签名.

    Args:
        data: 原始数据字节数组
        signature_b64: Base64 编码的签名字符串
        public_key_b64: Base64 编码的 RSA 公钥 (无 PEM 头尾)

    Returns:
        验签是否通过

    """
    pem_key = _wrap_pem(public_key_b64, "PUBLIC KEY")
    rsa_key = RSA.import_key(pem_key)

    hash_obj = SHA1.new(data)
    signature = base64.b64decode(signature_b64)

    try:
        pkcs1_15.new(rsa_key).verify(hash_obj, signature)
        return True
    except (ValueError, TypeError):
        return False


def _wrap_pem(key_b64: str, key_type: str) -> bytes:
    """
    将 base64 编码的密钥包装为 PEM 格式.

    Args:
        key_b64: Base64 编码的密钥内容 (无头尾标记)
        key_type: 密钥类型, 如 "RSA PRIVATE KEY" 或 "PUBLIC KEY"

    Returns:
        PEM 格式的密钥字节串

    """
    # 确保 base64 内容没有换行，然后按 64 字符分行
    key_b64_clean = key_b64.replace("\n", "").replace("\r", "").replace(" ", "")
    lines = [key_b64_clean[i : i + 64] for i in range(0, len(key_b64_clean), 64)]
    pem = f"-----BEGIN {key_type}-----\n"
    pem += "\n".join(lines)
    pem += f"\n-----END {key_type}-----"
    return pem.encode("utf-8")
