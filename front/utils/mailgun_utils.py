import hashlib
import hmac
import os
import time

import httpx

MAX_TIMESTAMP_AGE_SECONDS = 300  # 5 minutes
STORAGE_TIMEOUT_SECONDS = 10


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


def get_field(payload: dict, *names: str) -> str:
    """Read one field of a Mailgun payload, whatever spelling it came in.

    The stored-message API answers with RFC casing (`From`, `Message-Id`), an inbound route POSTs
    its own lowercase names (`from`, `recipient`) — the same field, two spellings.
    """
    lowered = {str(key).lower(): value for key, value in payload.items()}
    for name in names:
        value = lowered.get(name.lower())
        if value:
            return str(value)
    return ''


def fetch_stored_message(storage_url: str) -> dict | None:
    """Download the mail body an event webhook only points at.

    Mailgun's event payload carries headers, never the content: it hands out a storage URL instead,
    behind the private API key — the webhook signing key authenticates no API call. Returns None on
    any failure, which the caller must treat as transient: the message is only kept a few days.
    """
    api_key = os.environ.get('MAILGUN_API_KEY', '')
    if not api_key:
        print("Cannot fetch stored message: MAILGUN_API_KEY is not set")
        return None

    try:
        response = httpx.get(storage_url, auth=('api', api_key),
                             headers={'Accept': 'application/json'},
                             timeout=STORAGE_TIMEOUT_SECONDS)
    except httpx.HTTPError as e:
        print(f"Error fetching stored message {storage_url}: {e}")
        return None

    if response.status_code != 200:
        print(f"Error fetching stored message {storage_url}: "
              f"{response.status_code} - {response.text}")
        return None

    return response.json()
