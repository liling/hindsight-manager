import base64
import os

from gmssl.sm4 import CryptSM4, SM4_DECRYPT, SM4_ENCRYPT


def encrypt_sm4(plaintext: str, key: bytes) -> str:
    """Encrypt plaintext using SM4-CBC with random IV.

    Output: base64(IV_16bytes + ciphertext).
    """
    iv = os.urandom(16)
    sm4 = CryptSM4()
    sm4.set_key(key, SM4_ENCRYPT)
    ciphertext = sm4.crypt_cbc(iv, plaintext.encode())
    return base64.b64encode(iv + ciphertext).decode()


def decrypt_sm4(ciphertext_b64: str, key: bytes) -> str:
    """Decrypt SM4-CBC ciphertext. Input: base64(IV + ciphertext)."""
    raw = base64.b64decode(ciphertext_b64)
    iv = raw[:16]
    ciphertext = raw[16:]

    sm4 = CryptSM4()
    sm4.set_key(key, SM4_DECRYPT)
    plaintext = sm4.crypt_cbc(iv, ciphertext)
    return plaintext.decode()