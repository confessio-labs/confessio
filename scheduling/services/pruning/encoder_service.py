"""Service layer for the fine-tuned V2 Encoder.

Dev/prod split:
- `train_encoder` (dev, NO DB writes): fine-tune on a local prod-dump, then push the body +
  tokenizer + a `meta.json` (accuracies + the small head weights) to a private HF repo.
- `promote_encoder` (run on prod, or locally to test): pull `meta.json` from HF, create the
  `Encoder` row + the two head `Classifier`s in THIS database, significance-check vs the current
  PROD encoder, and flip PROD. It does NOT re-embed — re-embedding is lazy: on-the-fly at classify
  time and persisted in bulk by `reclassify_sentences`.
"""
import json
import os
import shutil
import threading
from pathlib import Path

from django.conf import settings

from scheduling.models.pruning_models import Classifier, Encoder, Sentence
from scheduling.services.pruning.classifier_target_service import get_target_enum
from scheduling.utils.stat_utils import is_significantly_different
from scheduling.workflows.pruning.encoder import FineTunedEncoder, TorchHeadModel

DEFAULT_HF_REPO_ID = os.environ.get("ENCODER_HF_REPO_ID", "confessio-labs/pruning-v2-encoder")
DEFAULT_BASE_MODEL = "camembert/camembert-large"
META_FILE = "meta.json"

# Most recent train's artifacts are staged here before the HF push, so a failed upload can be
# retried with `push_encoder` (no retraining).
ENCODER_WEIGHTS_DIR = Path(os.environ.get(
    "ENCODER_WEIGHTS_DIR", str(Path(settings.BASE_DIR) / ".encoder_weights")))

# Targets that run on the fine-tuned encoder (action stays on the sentence-transformer).
ENCODER_TARGETS = {Classifier.Target.TEMPORAL: 'temporal',
                   Classifier.Target.CONFESSION: 'confession'}

_prod = None  # cached (Encoder, FineTunedEncoder)
_prod_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Inference: the cached PROD encoder
# ---------------------------------------------------------------------------

def get_prod_encoder_model() -> Encoder:
    """The current PROD Encoder row, or raise if none exists yet."""
    try:
        return Encoder.objects.filter(status=Encoder.Status.PROD).latest('updated_at')
    except Encoder.DoesNotExist:
        raise ValueError("No encoder in production. Run train_encoder + promote_encoder first.")


def build_finetuned_encoder(encoder: Encoder) -> FineTunedEncoder:
    return FineTunedEncoder(encoder.hf_repo_id, encoder.hf_revision, encoder.base_model)


def get_prod_encoder() -> tuple[Encoder, FineTunedEncoder]:
    """Cached (Encoder, FineTunedEncoder) for the PROD encoder (loaded from HF once)."""
    global _prod
    if _prod is None:
        with _prod_lock:
            if _prod is None:
                encoder = get_prod_encoder_model()
                print(f'Loading PROD encoder {encoder.uuid} from {encoder.hf_repo_id}...')
                _prod = (encoder, build_finetuned_encoder(encoder))
    return _prod


# ---------------------------------------------------------------------------
# Developer (dev): train + push to HF (no DB writes)
# ---------------------------------------------------------------------------

def build_encoder_dataset() -> tuple[list, dict]:
    """Sentences with BOTH human labels feed the joint multi-task fine-tune."""
    sentences = list(Sentence.objects.filter(human_temporal__isnull=False,
                                             human_confession__isnull=False).all())
    lines = [s.line for s in sentences]
    labels_by_task = {'temporal': [s.human_temporal for s in sentences],
                      'confession': [s.human_confession for s in sentences]}
    return lines, labels_by_task


def _staging_dir() -> Path:
    return ENCODER_WEIGHTS_DIR / 'staging'


def _head_pickle(model, task: str, target_enum) -> str:
    head_model = TorchHeadModel[target_enum](target_enum.list_items())
    head_model.head = model.heads[task]
    return head_model.to_pickle()


def _build_meta(model, metrics: dict, base_model: str) -> dict:
    return {
        'base_model': base_model,
        'dimensions': model.body.config.hidden_size,
        'test_size': metrics['test_size'],
        'accuracy_temporal': metrics['accuracy_temporal'],
        'accuracy_confession': metrics['accuracy_confession'],
        # head weights travel in the meta (tiny, ~15 KB base64 each)
        'heads': {task: _head_pickle(model, task, get_target_enum(target))
                  for target, task in ENCODER_TARGETS.items()},
    }


def _upload_folder_to_hf(folder: Path, repo_id: str, attempts: int = 3) -> str:
    import time
    from huggingface_hub import HfApi
    token = os.environ.get("HF_TOKEN")
    if not token:
        raise ValueError("HF_TOKEN env var is required to push encoder weights")
    api = HfApi(token=token)
    last_exc = None
    for attempt in range(attempts):
        try:
            api.create_repo(repo_id, private=True, exist_ok=True, repo_type='model')
            commit = api.upload_folder(repo_id=repo_id, folder_path=str(folder),
                                       repo_type='model')
            return commit.oid
        except Exception as exc:  # transient network errors (e.g. EADDRNOTAVAIL) -> retry
            last_exc = exc
            print(f"HF upload attempt {attempt + 1}/{attempts} failed: {exc}", flush=True)
            if attempt < attempts - 1:
                time.sleep(10)
    raise last_exc


def stage_encoder_artifacts(model, tokenizer, meta: dict) -> Path:
    """Save body + tokenizer + meta.json to the staging dir (persisted before any network call)."""
    staging = _staging_dir()
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    model.body.save_pretrained(staging)
    tokenizer.save_pretrained(staging)
    (staging / META_FILE).write_text(json.dumps(meta))
    return staging


def push_staging_to_hf(repo_id: str = DEFAULT_HF_REPO_ID) -> str:
    """(Re)upload the staged artifacts to HF. Retries a push that failed without retraining."""
    staging = _staging_dir()
    if not (staging / META_FILE).exists():
        raise ValueError(f"No staged artifacts in {staging}; run train_encoder first")
    return _upload_folder_to_hf(staging, repo_id)


def train_and_stage_encoder(base_model: str = DEFAULT_BASE_MODEL) -> dict:
    """Fine-tune and stage artifacts locally (body + tokenizer + meta.json). NO database writes,
    NO network. Returns metrics. The caller pushes separately (so a failed upload never hides the
    training result and is retryable via push_encoder)."""
    # Imported lazily: train_encoder pulls scikit-learn, a dev-only dependency. Keeping it out of
    # the module scope keeps the prod inference path (classify_sentence_service) free of it.
    from scheduling.workflows.pruning.train_encoder import train_multitask

    lines, labels_by_task = build_encoder_dataset()
    model, tokenizer, metrics = train_multitask(lines, labels_by_task, base_model=base_model)
    meta = _build_meta(model, metrics, base_model)
    stage_encoder_artifacts(model, tokenizer, meta)
    return metrics


# ---------------------------------------------------------------------------
# Developer (prod): register from HF + promote (no re-embed)
# ---------------------------------------------------------------------------

def create_encoder_from_hf(repo_id: str, revision: str | None = None) -> Encoder:
    """Download meta.json from HF and create a DRAFT Encoder + its two head Classifiers in THIS
    database. Portable across dev/prod (keyed by HF repo, not a dev-DB uuid)."""
    from huggingface_hub import HfApi, hf_hub_download
    token = os.environ.get("HF_TOKEN")
    api = HfApi(token=token)
    if revision is None:
        revision = api.model_info(repo_id, token=token).sha
    meta_path = hf_hub_download(repo_id, META_FILE, revision=revision, token=token)
    meta = json.loads(Path(meta_path).read_text())

    encoder = Encoder(
        status=Encoder.Status.DRAFT,
        base_model=meta['base_model'],
        hf_repo_id=repo_id,
        hf_revision=revision,
        dimensions=meta['dimensions'],
    )
    encoder.save()

    for target, task in ENCODER_TARGETS.items():
        target_enum = get_target_enum(target)
        Classifier(
            transformer_name=meta['base_model'],
            encoder=encoder,
            status=Classifier.Status.DRAFT,
            target=target,
            different_labels=target_enum.list_items(),
            pickle=meta['heads'][task],
            accuracy=meta[f'accuracy_{task}'],
            test_size=meta['test_size'],
        ).save()

    return encoder


def _head_for(encoder: Encoder, target: Classifier.Target) -> Classifier | None:
    """The head Classifier of `encoder` for `target`: its PROD head if the encoder is live, else the
    latest (a freshly-registered DRAFT encoder whose heads aren't promoted yet)."""
    qs = Classifier.objects.filter(encoder=encoder, target=target)
    return qs.filter(status=Classifier.Status.PROD).order_by('-created_at').first() \
        or qs.order_by('-created_at').first()


def is_encoder_promotable(encoder: Encoder, current: Encoder) -> tuple[bool, str]:
    """Promote if significantly better on >=1 target and not significantly worse on the other.
    Per-task accuracy is read from each encoder's linked head Classifier. V2 heads are only ever
    set PROD by promote_encoder (no nightly retrain), so a PROD head's accuracy is the honest
    held-out joint-training number -> this compares honest-vs-honest."""
    verdicts = []
    sig_better, sig_worse = False, False
    for target in (Classifier.Target.TEMPORAL, Classifier.Target.CONFESSION):
        new_head, old_head = _head_for(encoder, target), _head_for(current, target)
        if new_head is None or old_head is None:
            verdicts.append(f"{target}: missing head")
            continue
        significant = is_significantly_different(new_head.accuracy, old_head.accuracy,
                                                 new_head.test_size, old_head.test_size)
        verdicts.append(f"{target}: {old_head.accuracy:.4f} -> {new_head.accuracy:.4f}"
                        f"{' (significant)' if significant else ''}")
        if significant and new_head.accuracy > old_head.accuracy:
            sig_better = True
        if significant and new_head.accuracy < old_head.accuracy:
            sig_worse = True
    return (sig_better and not sig_worse), " | ".join(verdicts)


def promote_encoder(encoder: Encoder, force: bool = False) -> tuple[bool, str]:
    """Flip the official encoder: significance-check vs current PROD, set this Encoder + its heads
    to PROD (demote the previous). Does NOT re-embed — that happens lazily (classify + reclassify).
    Returns (promoted, message)."""
    current = Encoder.objects.filter(status=Encoder.Status.PROD) \
        .exclude(uuid=encoder.uuid).order_by('-updated_at').first()

    if current is not None and not force:
        ok, message = is_encoder_promotable(encoder, current)
        if not ok:
            return False, f"Not promoted ({message}). Use --force to override."

    if current is not None:
        current.status = Encoder.Status.DRAFT
        current.save()
    encoder.status = Encoder.Status.PROD
    encoder.save()

    global _prod
    _prod = None  # invalidate cache in this process

    for classifier in Classifier.objects.filter(encoder=encoder,
                                                status=Classifier.Status.DRAFT):
        classifier.status = Classifier.Status.PROD
        classifier.save()

    return True, "Promoted to PROD (re-embedding will happen lazily via reclassify_sentences)."
