from crawling.workflows.download.download_content import get_content_from_url
from crawling.workflows.refine.refine_content import refine_confession_content
from scheduling.public_workflow import scheduling_extract_v2_refined_content


def get_extracted_v2_html_list(html_content: str) -> list[str] | None:
    refined_content = refine_confession_content(html_content)
    if refined_content is None:
        return None

    return scheduling_extract_v2_refined_content(refined_content)


def get_fresh_extracted_html_list(url) -> list[str] | None:
    content = get_content_from_url(url)
    if content is None:
        return None
    html_content, _ = content

    return get_extracted_v2_html_list(html_content)


if __name__ == '__main__':
    url_ = ('https://www.paroisses-plessis-clamart.fr/')
    extracted_html_list_ = get_fresh_extracted_html_list(url_)

    print()
    print(url_)
    if extracted_html_list_ is not None:
        for extracted_html_ in extracted_html_list_:
            print(extracted_html_)
    else:
        print('Empty extracted html list')
