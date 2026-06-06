from bs4 import BeautifulSoup

from crawling.public_workflow import crawling_get_content_from_url


def get_page_title(url):
    content = crawling_get_content_from_url(url)
    if content is None:
        return None
    html, _ = content

    try:
        soup = BeautifulSoup(html, 'html.parser')
    except Exception as e:
        print(e)
        return None

    title = soup.find('title')
    if not title:
        return None

    title_name = title.string.strip()
    print(f'got title {title_name}')

    return title_name


if __name__ == '__main__':
    print(get_page_title('http://www.montsdelamadeleine.fr/'))
