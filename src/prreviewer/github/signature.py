import hashlib
import hmac


def verify_signature(payload: bytes, signature_header: str | None, secret: str) -> bool:
    """Verify GitHub's `X-Hub-Signature-256` header over the raw request body.
    Constant-time compare; a webhook secret must be configured."""
    if not signature_header or not secret:
        return False
    if not signature_header.startswith("sha256="):
        return False

    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    provided = signature_header.removeprefix("sha256=")
    return hmac.compare_digest(expected, provided)
