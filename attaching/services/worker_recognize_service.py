from attaching.models import Image, PdfRecognition
from attaching.services.image_service import get_image_html
from attaching.services.upload_image_service import get_image_public_url
from attaching.workflows.recognize.recognize_image_with_llm import (get_html_from_image, get_prompt,
                                                                    get_llm_model)
from attaching.workflows.recognize.recognize_image_with_pdf import (get_html_from_pdf,
                                                                    get_pdf_prompt,
                                                                    get_pdf_llm_model)
from core.utils.llm_utils import LLMProvider
from crawling.public_workflow import crawling_get_extracted_html_list
from scheduling.public_service import scheduling_create_pruning
from scheduling.utils.hash_utils import hash_string_to_hex, hash_bytes_to_sha256_hex


def recognize_image(image: Image):
    if image.llm_provider is not None:
        print(f'Image {image.uuid} already recognized with LLM')
        return

    print(f'Recognizing image {image.uuid} with LLM')

    prompt = get_prompt()
    prompt_hash = hash_string_to_hex(prompt)
    llm_provider = LLMProvider.OPENAI
    llm_model = get_llm_model()
    llm_html, llm_error_details = get_html_from_image(get_image_public_url(image),
                                                      prompt, llm_provider, llm_model)

    if llm_error_details:
        image.llm_error_details = llm_error_details
    else:
        image.llm_html = llm_html
    image.prompt_hash = prompt_hash
    image.llm_provider = llm_provider
    image.llm_model = llm_model
    image.save()


def recognize_pdf(pdf_url: str, pdf_bytes: bytes) -> str:
    pdf_sha256 = hash_bytes_to_sha256_hex(pdf_bytes)

    existing = PdfRecognition.objects.filter(pdf_sha256=pdf_sha256).first()
    if existing is not None and existing.llm_error_detail is None:
        print(f'Pdf {pdf_url} already recognized with LLM')
        return existing.llm_html

    print(f'Recognizing pdf {pdf_url} with LLM')

    prompt = get_pdf_prompt()
    prompt_hash = hash_string_to_hex(prompt)
    llm_provider = LLMProvider.OPENAI
    llm_model = get_pdf_llm_model()
    llm_html, llm_error_detail = get_html_from_pdf(pdf_bytes, prompt, llm_provider, llm_model)

    pdf_recognition = PdfRecognition(
        pdf_url=pdf_url,
        pdf_sha256=pdf_sha256,
        llm_html=llm_html,
        llm_error_detail=llm_error_detail,
        prompt_hash=prompt_hash,
        llm_provider=llm_provider,
        llm_model=llm_model,
    )
    pdf_recognition.save()

    return pdf_recognition.llm_html


def extract_image(image: Image):
    extracted_html_list = crawling_get_extracted_html_list(get_image_html(image))
    if not extracted_html_list:
        return

    prunings = []
    for extracted_html_item in extracted_html_list:
        prunings.append(scheduling_create_pruning(extracted_html_item))

    image.prunings.clear()
    for pruning in prunings:
        image.prunings.add(pruning)
