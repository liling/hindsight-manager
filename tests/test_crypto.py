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
    """CBC with IV may decrypt to garbage data or raise exception."""
    key1 = bytes.fromhex("0123456789abcdef0123456789abcdef")
    key2 = bytes.fromhex("fedcba9876543210fedcba9876543210")
    ciphertext = encrypt_sm4("test-data", key1)

    # Wrong key should either raise UnicodeDecodeError (invalid UTF-8)
    # or return data != original plaintext
    try:
        result = decrypt_sm4(ciphertext, key2)
        assert result != "test-data", "Wrong key should not produce correct plaintext"
    except UnicodeDecodeError:
        # This is expected when wrong key produces invalid UTF-8
        pass


def test_encrypt_different_plaintexts_different_ciphertexts():
    key = bytes.fromhex("0123456789abcdef0123456789abcdef")
    ct1 = encrypt_sm4("plaintext_a", key)
    ct2 = encrypt_sm4("plaintext_b", key)
    assert ct1 != ct2


def test_encrypt_long_plaintext():
    key = bytes.fromhex("0123456789abcdef0123456789abcdef")
    plaintext = "x" * 200
    assert decrypt_sm4(encrypt_sm4(plaintext, key), key) == plaintext


def test_cbc_same_plaintext_different_ciphertext():
    """CBC with random IV must produce different ciphertext each time."""
    key = bytes.fromhex("0123456789abcdef0123456789abcdef")
    plaintext = "hello world"
    ct1 = encrypt_sm4(plaintext, key)
    ct2 = encrypt_sm4(plaintext, key)
    assert ct1 != ct2


def test_cbc_ciphertext_longer_than_ecb():
    """CBC ciphertext includes 16-byte IV prefix."""
    key = bytes.fromhex("0123456789abcdef0123456789abcdef")
    plaintext = "short"
    ct_b64 = encrypt_sm4(plaintext, key)
    import base64
    raw = base64.b64decode(ct_b64)
    # IV (16) + at least one block (16) = 32 bytes minimum
    assert len(raw) >= 32


def test_cbc_roundtrip_empty_string():
    """CBC handles empty plaintext."""
    key = bytes.fromhex("0123456789abcdef0123456789abcdef")
    ct = encrypt_sm4("", key)
    assert decrypt_sm4(ct, key) == ""
