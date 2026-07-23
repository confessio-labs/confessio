import string

import pymupdf


def has_bad_encoding(text: str) -> bool:
    words = text.split()
    for w in words:
        if not w or len(w) <= 1:
            continue

        if w.startswith('’'):
            return True

    return False


def convert_text_to_html(raw_text: str) -> str:
    """Change \n to <br> and remove extra spaces."""
    # Remove extra spaces
    cleaned_text = ' '.join(raw_text.split(sep=' '))

    # Replace new lines with <br>, if starting or ending with a punctuation
    lines = []
    for line in cleaned_text.split('\n'):
        if not line:
            lines.append('<br>')
            continue

        has_digit = any(map(lambda c: c.isdigit(), line))
        if line[0] in string.punctuation or has_digit:
            lines.append('<br>')

        lines.append(' ')
        lines.append(line)

        if line[-1] in string.punctuation or has_digit:
            lines.append('<br>')

    return ''.join(lines)


def extract_text_from_doc(doc) -> str:
    text = ''
    for page_num in range(len(doc)):
        page = doc[page_num]
        text += extract_text_from_pdf_page(page) + '\n'

    doc.close()

    if has_bad_encoding(text):
        print('bad encoding, ignoring this pdf. In the future we shall use OCR')
        return ''

    return convert_text_to_html(text)


def find_split_lines(blocks_coords, axis=1):
    """
    Find split lines along axis:
    axis=1 -> horizontal (y)
    axis=0 -> vertical (x)
    """
    # choose relevant coords
    idx0, idx1 = (1, 3) if axis == 1 else (0, 2)

    candidates = set()
    for b in blocks_coords:
        candidates.add(b[idx0])  # top or left
        candidates.add(b[idx1])  # bottom or right

    valid = []
    for c in sorted(candidates):
        ok = True
        for b in blocks_coords:
            if not (b[idx1] <= c or b[idx0] >= c):
                ok = False
                break
        if ok:
            valid.append(c)
    return valid


def find_clip_areas(blocks_coords, page_rect):
    # First: horizontal splits
    y_splits = [page_rect[1]] + find_split_lines(blocks_coords, axis=1) + [page_rect[3]]
    y_splits = sorted(set(y_splits))

    clip_areas = []
    for y0, y1 in zip(y_splits[:-1], y_splits[1:]):
        # consider blocks in this vertical band
        band_blocks = [b for b in blocks_coords if not (b[3] <= y0 or b[1] >= y1)]
        if not band_blocks:
            continue

        x_splits = [page_rect[0]] + find_split_lines(band_blocks, axis=0) + [page_rect[2]]
        x_splits = sorted(set(x_splits))
        for x0, x1 in zip(x_splits[:-1], x_splits[1:]):
            # keep only if at least one block intersects this rectangle
            area_blocks = [b for b in band_blocks if not (b[2] <= x0 or b[0] >= x1)]
            if area_blocks:
                clip_areas.append((x0, y0, x1, y1))

    return clip_areas


def blocks_are_in_natural_order(blocks):
    coords = [b[:2] for b in blocks]

    max_x = coords[0][0]
    max_y = coords[0][1]
    for i in range(len(coords) - 1):
        x1, y1 = coords[i]
        x2, y2 = coords[i + 1]

        if not (y2 > y1 or x2 > x1) or not (x2 > max_x or y2 > max_y):
            return False

        max_x = max(max_x, x2)
        max_y = max(max_y, y2)

    return True


def extract_text_from_pdf_page(page) -> str:
    non_empty_text_blocks = [b for b in page.get_text("blocks") if b[6] == 0 and b[4].strip()]
    if not non_empty_text_blocks:
        return ''

    if not blocks_are_in_natural_order(non_empty_text_blocks):
        blocks_coords = [b[:4] for b in non_empty_text_blocks]
        areas = find_clip_areas(blocks_coords, page.rect)
        return '<br>'.join(page.get_text('text', sort=True, clip=area) for area in areas)

    return page.get_text('text', sort=False)


def extract_text_from_pdf_file(pdf_file: str) -> str:
    doc = pymupdf.open(pdf_file)
    return extract_text_from_doc(doc)


def extract_text_from_pdf_bytes(raw_content: bytes) -> str | None:
    try:
        doc = pymupdf.open(stream=raw_content, filetype="pdf")
    except pymupdf.FileDataError as e:
        print('Could not open pdf', e)
        return None

    return extract_text_from_doc(doc)
