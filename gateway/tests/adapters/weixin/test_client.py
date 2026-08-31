"""Weixin media cryptography compatibility tests."""

import base64

from Crypto.Cipher import AES

from gateway.adapters.weixin.client import _pad, _unpad, parse_media_key


def test_media_key_formats_and_pkcs7_round_trip() -> None:
    key = bytes(range(16))
    direct = base64.b64encode(key).decode()
    encoded_hex = base64.b64encode(key.hex().encode()).decode()
    assert parse_media_key(direct) == key
    assert parse_media_key(encoded_hex) == key

    content = b"weixin-media-content"
    encrypted = AES.new(key, AES.MODE_ECB).encrypt(_pad(content))
    assert _unpad(AES.new(key, AES.MODE_ECB).decrypt(encrypted)) == content
