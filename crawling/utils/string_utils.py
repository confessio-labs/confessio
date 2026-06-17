def is_below_byte_limit(s, byte_limit=2704):
    return len(s.encode('utf-8')) < byte_limit


def remove_unsafe_chars(text: str) -> str:
    if not text:
        return text

    return text.replace('\udce7', '').replace('\x00', '')
