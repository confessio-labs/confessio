def is_below_byte_limit(s, byte_limit=2704):
    return len(s.encode('utf-8')) < byte_limit


def remove_unsafe_chars(text: str) -> str:
    if not text:
        return text

    return text.replace('\udce7', '').replace('\x00', '')


def strip_null_bytes(value):
    """Recursively remove NUL/surrogate chars that Postgres text/jsonb reject.

    Walks JSON-able structures (dict/list/str); other scalars pass through unchanged.
    """
    if isinstance(value, str):
        return remove_unsafe_chars(value)
    if isinstance(value, dict):
        return {strip_null_bytes(k): strip_null_bytes(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [strip_null_bytes(v) for v in value]
    return value
