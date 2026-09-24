import hashlib
import hmac

from prreviewer.github.signature import verify_signature

SECRET = "test-secret"
BODY = b'{"hello": "world"}'


def _sign(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_valid_signature_passes():
    assert verify_signature(BODY, _sign(BODY, SECRET), SECRET) is True


def test_wrong_secret_fails():
    assert verify_signature(BODY, _sign(BODY, "wrong-secret"), SECRET) is False


def test_tampered_body_fails():
    signature = _sign(BODY, SECRET)
    assert verify_signature(b'{"hello": "mallory"}', signature, SECRET) is False


def test_missing_header_fails():
    assert verify_signature(BODY, None, SECRET) is False


def test_missing_secret_fails():
    assert verify_signature(BODY, _sign(BODY, SECRET), "") is False


def test_malformed_header_fails():
    assert verify_signature(BODY, "not-a-real-signature", SECRET) is False
