"""Env guards that must be set before transformers / huggingface_hub is imported.

Imported (for its side effects) by every module that can reach the HF stack: the encoder
workflow, the encoder training workflow, and the encoder service.
"""
import os

os.environ.setdefault("USE_TF", "0")  # transformers: torch-only backend
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")  # avoid the flaky Xet download backend
os.environ.setdefault("TRANSFORMERS_NO_ADVISORY_WARNINGS", "1")
