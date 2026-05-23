"""Tests for Shenbianyun crypto helpers."""

import base64
from unittest import TestCase

from Crypto.PublicKey import RSA

from shenbianyun.crypto import des_decrypt, des_encrypt, rsa_sign, rsa_verify

TEST_DES_KEY = "0123456789ABCDEFFEDCBA9876543210"


def _rsa_keypair():
    """Generate a test RSA key pair."""
    key = RSA.generate(1024)  # noqa: S505
    private_key_b64 = base64.b64encode(key.export_key("DER")).decode()
    public_key_b64 = base64.b64encode(key.publickey().export_key("DER")).decode()
    return private_key_b64, public_key_b64


class CryptoHelperTests(TestCase):
    """Tests for DES encryption and RSA signing helpers."""

    def test_des_encrypt_decrypt_roundtrip(self):
        """Encrypted data can be decrypted back to the original bytes."""
        plaintext = "你好，身边云！Hello, world!".encode()

        ciphertext = des_encrypt(plaintext, TEST_DES_KEY)
        decrypted = des_decrypt(ciphertext, TEST_DES_KEY)

        self.assertEqual(decrypted, plaintext)

    def test_des_encrypt_produces_different_output(self):
        """Ciphertext differs from plaintext and remains block aligned."""
        plaintext = b"sensitive_data_payload_1234567890"

        ciphertext = des_encrypt(plaintext, TEST_DES_KEY)

        self.assertNotEqual(ciphertext, plaintext)
        self.assertEqual(len(ciphertext) % 8, 0)

    def test_des_decrypt_invalid_data(self):
        """Invalid ciphertext raises from the crypto backend."""
        invalid_ciphertext = b"not-a-valid-des-ciphertext-block"

        with self.assertRaises(Exception):  # noqa: B017
            des_decrypt(invalid_ciphertext, TEST_DES_KEY)

    def test_rsa_sign_verify_roundtrip(self):
        """A signature verifies with the matching public key."""
        private_key_b64, public_key_b64 = _rsa_keypair()
        data = b"data-to-be-signed-12345"

        signature = rsa_sign(data, private_key_b64)

        self.assertIsInstance(signature, str)
        self.assertGreater(len(signature), 0)
        self.assertIs(rsa_verify(data, signature, public_key_b64), True)

    def test_rsa_verify_tampered_data(self):
        """A signature does not verify for modified data."""
        private_key_b64, public_key_b64 = _rsa_keypair()
        data = b"original-data-payload"
        signature = rsa_sign(data, private_key_b64)

        tampered = b"tampered-data-payload"

        self.assertIs(rsa_verify(tampered, signature, public_key_b64), False)

    def test_rsa_verify_wrong_key(self):
        """A signature does not verify with an unrelated public key."""
        private_key_b64, _ = _rsa_keypair()
        _, wrong_public_key_b64 = _rsa_keypair()
        data = b"data-signed-by-keypair-1"

        signature = rsa_sign(data, private_key_b64)

        self.assertIs(rsa_verify(data, signature, wrong_public_key_b64), False)
