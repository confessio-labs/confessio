from scheduling.workflows.pruning.extract_interface import BaseExtractInterface, ExtractMode
from scheduling.workflows.pruning.extract_v2.extract_content import ExtractV2Interface
from scheduling.workflows.pruning.extract_v2.qualify_line_interfaces import \
    RegexQualifyLineInterface


def extract_v2_refined_content(refined_content: str) -> list[str] | None:
    return extract_and_join(refined_content, ExtractV2Interface(RegexQualifyLineInterface()))


def extract_and_join(refined_content: str, extract_interface: BaseExtractInterface = None
                     ) -> list[str] | None:
    paragraphs_lines_and_indices = extract_interface.extract_paragraphs_lines_and_indices(
        refined_content, ExtractMode.EXTRACT)
    if not paragraphs_lines_and_indices:
        return None

    extracted_html_list = []
    for paragraph_lines, paragraph_indices in paragraphs_lines_and_indices:
        extracted_html_list.append('<br>\n'.join(paragraph_lines))

    return extracted_html_list
