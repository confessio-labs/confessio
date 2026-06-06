import base64
import os

import openai
import pymupdf
from openai import BadRequestError

from attaching.workflows.recognize.recognize_image_with_llm import remove_triple_quotes
from core.utils.llm_utils import LLMProvider


def get_pdf_prompt() -> str:
    return """Convert this PDF (given as one image per page) to HTML. Just output a valid HTML.
    Do not include any additional text or explanations.
    If there is no text in the PDF, just return an empty HTML document with <html></html> tags."""


def get_pdf_llm_model() -> str:
    return "gpt-4o-mini"


def convert_pdf_to_images(pdf_bytes: bytes) -> list[bytes]:
    """Convert each page of a PDF into a PNG image (rendered at 2x zoom for readability)."""
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    images = []
    for page in doc:
        pix = page.get_pixmap(matrix=pymupdf.Matrix(2, 2))
        images.append(pix.tobytes("png"))
    return images


def get_html_from_pdf(pdf_bytes: bytes, prompt: str, llm_provider: LLMProvider,
                      llm_model: str, max_attempts: int = 3) -> tuple[str | None, str | None]:
    assert llm_provider == LLMProvider.OPENAI
    images = convert_pdf_to_images(pdf_bytes)

    content = [{"type": "input_text", "text": prompt}]
    for image in images:
        b64 = base64.b64encode(image).decode("utf-8")
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

        return remove_triple_quotes(response.output_text), None
    except BadRequestError as e:
        if 'Timeout while downloading' in str(e):
            if max_attempts > 0:
                print(f"Retrying after error {e}. {max_attempts} attempt(s) remaining...")
                return get_html_from_pdf(pdf_bytes, prompt, llm_provider, llm_model,
                                         max_attempts - 1)
        print(f"Error processing pdf: {e}")
        return None, str(e)
