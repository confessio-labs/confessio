import base64
import os

from attaching.workflows.recognize.recognize_image_with_llm import remove_triple_quotes
from core.utils.llm_utils import LLMProvider

# openai (~0.24 s) and pymupdf (~0.06 s) are imported lazily: this module is worker-only but is
# reachable from the server startup path (attaching.signals -> attaching.public_service ->
# worker_recognize_service).


def get_pdf_prompt() -> str:
    return """Convert this PDF (given as one image per page) to HTML. Just output a valid HTML.
    Do not include any additional text or explanations.
    If there is no text in the PDF, just return an empty HTML document with <html></html> tags."""


def get_pdf_llm_model() -> str:
    return "gpt-4o-mini"


def convert_pdf_to_images(pdf_bytes: bytes) -> tuple[list[bytes], int]:
    """Convert each page of a PDF into a PNG image (rendered at 1.5x zoom for readability)."""
    import pymupdf

    images = []
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        nb_pages = doc.page_count
        for page in doc:
            pix = page.get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5))
            images.append(pix.tobytes("png"))
            pix = None  # free the raw bitmap before rendering the next page
    return images, nb_pages


def get_html_from_pdf(pdf_bytes: bytes, prompt: str, llm_provider: LLMProvider,
                      llm_model: str, max_attempts: int = 3
                      ) -> tuple[str | None, str | None, int]:
    import openai
    from openai import BadRequestError

    assert llm_provider == LLMProvider.OPENAI
    images, nb_pages = convert_pdf_to_images(pdf_bytes)

    content = [{"type": "input_text", "text": prompt}]
    while images:
        image = images.pop(0)
        b64 = base64.b64encode(image).decode("utf-8")
        del image
        content.append({"type": "input_image", "image_url": f"data:image/png;base64,{b64}"})

    openai_client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY_RECOGNIZE"))

    try:
        response = openai_client.responses.create(
            model=llm_model,
            input=[
                {
                    "role": "user",
                    "content": content,
                }
            ],
            temperature=0.0,
        )

        return remove_triple_quotes(response.output_text), None, nb_pages
    except BadRequestError as e:
        if 'Timeout while downloading' in str(e):
            if max_attempts > 0:
                print(f"Retrying after error {e}. {max_attempts} attempt(s) remaining...")
                return get_html_from_pdf(pdf_bytes, prompt, llm_provider, llm_model,
                                         max_attempts - 1)
        print(f"Error processing pdf: {e}")
        return None, str(e), nb_pages
