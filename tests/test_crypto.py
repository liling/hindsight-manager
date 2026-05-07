import pytest

from hindsight_manager.crypto import decrypt_sm4, encrypt_sm4


def test_encrypt_decrypt_roundtrip():
    key = bytes.fromhex("0123456789abcdef0123456789abcdef")
    plaintext = "hsm_abc123secretkey456xyz789"
    ciphertext = encrypt_sm4(plaintext, key)
    assert ciphertext != plaintext
    assert decrypt_sm4(ciphertext, key) == plaintext


def test_encrypt_produces_base64():
    key = bytes.fromhex("0123456789abcdef0123456789abcdef")
    ciphertext = encrypt_sm4("test-data", key)
    import base64
    base64.b64decode(ciphertext)  # should not raise


def test_decrypt_wrong_key_raises():
    key1 = bytes.fromhex("0123456789abcdef0123456789abcdef")
    key2 = bytes.fromhex("fedcba9876543210fedcba9876543210")
    ciphertext = encrypt_sm4("test-data", key1)
    with pytest.raises(Exception):
        decrypt_sm4(ciphertext, key2)


def test_encrypt_different_plaintexts_different_ciphertexts():
    key = bytes.fromhex("0123456789abcdef0123456789abcdef")
    ct1 = encrypt_sm4("plaintext_a", key)
    ct2 = encrypt_sm4("plaintext_b", key)
    assert ct1 != ct2


def test_encrypt_long_plaintext():
    key = bytes.fromhex("0123456789abcdef0123456789abcdef")
    plaintext = "x" * 200
    assert decrypt_sm4(encrypt_sm4(plaintext, key), key) == plaintext
