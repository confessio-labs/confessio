"""Fine-tuned encoder (camembert-large) + per-task heads for V2 pruning.

- `FineTunedEncoder`: loads the PROD `Encoder`'s body from its private HF repo and turns a line
  into a 1024-d embedding (the <s>-token vector). Thread-safe singleton, like `get_transformer`.
- `Head` / `TorchHeadModel`: the small per-task classifier consuming that embedding. `Head` is the
  ONE shared definition reused by joint encoder training (`train_encoder.py`) and by cheap nightly
  head retraining, so head weights are interchangeable. `TorchHeadModel` implements the existing
  `MachineLearningInterface` so it drops into the training/inference flow next to `TensorFlowModel`.

Env note: torch must be imported before scipy/sklearn (macOS duplicate-OpenMP segfault), and
transformers must not load its TF backend. We set these guards at import time.
"""
import os

os.environ.setdefault("USE_TF", "0")  # transformers: torch-only backend
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")  # avoid the flaky Xet download backend
os.environ.setdefault("TRANSFORMERS_NO_ADVISORY_WARNINGS", "1")

import base64  # noqa: E402
import io  # noqa: E402
from typing import Generic, TypeVar  # noqa: E402

import numpy as np  # noqa: E402
import torch  # noqa: E402  MUST precede scipy/sklearn imports (OpenMP segfault guard)
import torch.nn as nn  # noqa: E402

from scheduling.workflows.pruning.train_and_predict import MachineLearningInterface  # noqa: E402
from scheduling.utils.enum_utils import StringEnum  # noqa: E402

E = TypeVar('E', bound=StringEnum)

MAX_LENGTH = 192
HEAD_EPOCHS = 40
HEAD_LR = 1e-3
HEAD_BATCH = 32

# The fine-tuned encoder's <s> embedding is already highly task-separable, so a plain linear head
# is the default (~17 KB pickle). Set False-> dense bottleneck head (RoBERTa-style, ~5 MB) only if
# validation shows the linear head loses accuracy. Both joint and nightly training use this flag.
HEAD_BOTTLENECK = False


class Head(nn.Module):
    """Classification head on the <s>-token embedding. `bottleneck=True` adds a RoBERTa-style
    dense->tanh layer; otherwise it is a single linear projection."""

    def __init__(self, hidden: int, n_labels: int, bottleneck: bool = HEAD_BOTTLENECK,
                 p: float = 0.1):
        super().__init__()
        self.dropout = nn.Dropout(p)
        self.dense = nn.Linear(hidden, hidden) if bottleneck else None
        self.out = nn.Linear(hidden, n_labels)

    def forward(self, x):
        x = self.dropout(x)
        if self.dense is not None:
            x = torch.tanh(self.dense(x))
            x = self.dropout(x)
        return self.out(x)


class TorchHeadModel(MachineLearningInterface[E], Generic[E]):
    """A `Head` trained on (frozen) encoder embeddings. Used for nightly head retraining and to
    wrap heads extracted from joint encoder training. Serialized as the head's torch state_dict."""

    def __init__(self, different_labels: list[E], epochs: int = HEAD_EPOCHS,
                 lr: float = HEAD_LR, batch_size: int = HEAD_BATCH):
        self.different_labels = different_labels
        self.epochs = epochs
        self.lr = lr
        self.batch_size = batch_size
        self.head: Head | None = None

    def _class_weights(self, y: torch.Tensor) -> torch.Tensor:
        counts = torch.tensor([(y == i).sum().item() for i in range(len(self.different_labels))],
                              dtype=torch.float32)
        counts = counts.clamp(min=1.0)
        w = counts.sum() / (len(self.different_labels) * counts)
        return w / w.mean()

    def fit(self, embeddings, labels: list[E]):
        torch.manual_seed(42)
        x = torch.tensor(np.array(embeddings), dtype=torch.float32)
        y = torch.tensor([self.different_labels.index(lab) for lab in labels], dtype=torch.long)

        self.head = Head(x.shape[1], len(self.different_labels))
        self.head.train()
        optim = torch.optim.AdamW(self.head.parameters(), lr=self.lr, weight_decay=0.01)
        loss_fn = nn.CrossEntropyLoss(weight=self._class_weights(y))

        n = x.shape[0]
        for _ in range(self.epochs):
            perm = torch.randperm(n)
            for start in range(0, n, self.batch_size):
                idx = perm[start:start + self.batch_size]
                optim.zero_grad()
                loss = loss_fn(self.head(x[idx]), y[idx])
                loss.backward()
                optim.step()

    def predict(self, embeddings) -> list[E]:
        assert self.head is not None, "Model is not trained/loaded"
        x = torch.tensor(np.array(embeddings), dtype=torch.float32)
        self.head.eval()
        with torch.no_grad():
            preds = self.head(x).argmax(dim=1).tolist()
        return [self.different_labels[i] for i in preds]

    def to_pickle(self) -> str:
        assert self.head is not None, "Model is not trained/loaded"
        buffer = io.BytesIO()
        torch.save({'hidden': self.head.out.in_features,
                    'n_labels': len(self.different_labels),
                    'bottleneck': self.head.dense is not None,
                    'state_dict': self.head.state_dict()}, buffer)
        return base64.b64encode(buffer.getvalue()).decode('utf-8')

    def from_pickle(self, pickle_as_str: str):
        buffer = io.BytesIO(base64.b64decode(pickle_as_str))
        data = torch.load(buffer, weights_only=False)
        self.head = Head(data['hidden'], data['n_labels'], bottleneck=data['bottleneck'])
        self.head.load_state_dict(data['state_dict'])
        self.head.eval()


class FineTunedEncoder:
    """Loads a fine-tuned camembert body from its HF repo and embeds lines into 1024-d vectors."""

    def __init__(self, hf_repo_id: str, hf_revision: str | None, base_model: str):
        from transformers import AutoModel, AutoTokenizer
        torch.set_num_threads(int(os.environ.get("TORCH_THREADS", "4")))
        self.hf_repo_id = hf_repo_id
        token = os.environ.get("HF_TOKEN")
        self.tokenizer = AutoTokenizer.from_pretrained(hf_repo_id, revision=hf_revision,
                                                       token=token)
        self.body = AutoModel.from_pretrained(hf_repo_id, revision=hf_revision, token=token)
        self.body.eval()

    def embed_batch(self, lines: list[str]) -> list[list]:
        enc = self.tokenizer(lines, truncation=True, max_length=MAX_LENGTH, padding=True,
                             return_tensors='pt')
        with torch.no_grad():
            out = self.body(input_ids=enc['input_ids'], attention_mask=enc['attention_mask'])
        return out.last_hidden_state[:, 0].cpu().numpy().tolist()

    def embed(self, line: str) -> list:
        return self.embed_batch([line])[0]
