import hashlib
import hmac
import os
import time

MAX_TIMESTAMP_AGE_SECONDS = 300  # 5 minutes


def validate_token(token: str, timestamp: int, signature: str) -> bool:
    # Reject stale requests (replay attack prevention)
    current_time = time.time()
    if abs(current_time - timestamp) > MAX_TIMESTAMP_AGE_SECONDS:
        print(f"Rejecting request with timestamp {timestamp} (too old), "
              f"current time is {current_time}")
        return False

    signing_key = os.environ['MAILGUN_WEBHOOK_SIGNING_KEY']
    expected = hmac.new(
        key=signing_key.encode(),
        msg=f"{timestamp}{token}".encode(),
        digestmod=hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(expected, signature)
