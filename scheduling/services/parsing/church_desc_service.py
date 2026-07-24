from registry.models import Church
from scheduling.utils.list_utils import get_desc_by_id


def get_church_desc_list(churches: list[Church]) -> list[str]:
    return list(set(church.get_desc() for church in churches))


def get_church_desc_by_id(churches: list[Church]) -> dict[int, str]:
    church_desc_list = get_church_desc_list(churches)
    return get_desc_by_id(church_desc_list)


def get_church_by_id(churches: list[Church]) -> dict[int, Church]:
    church_by_desc = {church.get_desc(): church for church in churches}
    church_desc_by_id = get_desc_by_id(list(church_by_desc.keys()))
    return {church_id: church_by_desc[desc] for church_id, desc in church_desc_by_id.items()}


def churches_have_desc_conflict(churches: list[Church]):
    return len(get_church_desc_list(churches)) != len(churches)
