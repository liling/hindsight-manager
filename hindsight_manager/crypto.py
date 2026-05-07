import base64

from gmssl.sm4 import CryptSM4, SM4_DECRYPT, SM4_ENCRYPT


def encrypt_sm4(plaintext: str, key: bytes) -> str:
    sm4 = CryptSM4()
    sm4.set_key(key, SM4_ENCRYPT)
    data = plaintext.encode()
    pad_len = 16 - (len(data) % 16)
    data += bytes([pad_len] * pad_len)
    ciphertext = sm4.crypt_ecb(data)
    return base64.b64encode(ciphertext).decode()


def decrypt_sm4(ciphertext_b64: str, key: bytes) -> str:
    sm4 = CryptSM4()
    sm4.set_key(key, SM4_DECRYPT)
    ciphertext = base64.b64decode(ciphertext_b64)
    plaintext_padded = sm4.crypt_ecb(ciphertext)
    pad_len = plaintext_padded[-1]
    return plaintext_padded[:-pad_len].decode()
