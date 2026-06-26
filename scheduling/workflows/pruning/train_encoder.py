"""Joint multi-task fine-tune of the camembert-large encoder + temporal & confession heads.

Ported from the validated experiment (one shared body + two heads, equal task loss, lr=1e-5,
warmup + gradient accumulation). Pure workflow: takes raw lines + labels, returns the trained
torch model, its tokenizer, and held-out accuracies. The service layer turns this into an
`Encoder` (body pushed to HF) + two `Classifier` heads.
"""
import os

os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
os.environ.setdefault("TRANSFORMERS_NO_ADVISORY_WARNINGS", "1")

import numpy as np  # noqa: E402
import torch  # noqa: E402  before sklearn (OpenMP guard)
import torch.nn as nn  # noqa: E402
from sklearn.metrics import accuracy_score  # noqa: E402
from sklearn.model_selection import train_test_split  # noqa: E402

from scheduling.workflows.pruning.encoder import Head, MAX_LENGTH  # noqa: E402
from scheduling.workflows.pruning.extract_v2.models import Temporal, EventMention  # noqa: E402

# task -> ordered label list (must match Classifier.different_labels for that target)
TASK_LABELS = {
    'temporal': Temporal.list_items(),
    'confession': EventMention.list_items(),
}
TASKS = list(TASK_LABELS.keys())


class MultiTaskEncoder(nn.Module):
    def __init__(self, model_name: str):
        super().__init__()
        from transformers import AutoModel
        self.body = AutoModel.from_pretrained(model_name)
        hidden = self.body.config.hidden_size
        self.heads = nn.ModuleDict(
            {t: Head(hidden, len(TASK_LABELS[t])) for t in TASKS})

    def forward(self, input_ids, attention_mask):
        out = self.body(input_ids=input_ids, attention_mask=attention_mask)
        cls = out.last_hidden_state[:, 0]
        return {t: head(cls) for t, head in self.heads.items()}


def _class_weights(label_idx: list[int], n_labels: int) -> torch.Tensor:
    counts = np.array([label_idx.count(i) for i in range(n_labels)], dtype="float32")
    counts = np.clip(counts, 1.0, None)
    w = counts.sum() / (n_labels * counts)
    return torch.tensor(w / w.mean(), dtype=torch.float32)


def train_multitask(lines: list[str], labels_by_task: dict,
                    base_model: str = 'camembert/camembert-large',
                    epochs: int = 5, lr: float = 1e-5, batch_size: int = 4,
                    grad_accum: int = 2, warmup_ratio: float = 0.1,
                    max_length: int = MAX_LENGTH, test_frac: float = 0.2, seed: int = 42):
    """Returns (model, tokenizer, metrics) where metrics has accuracy_temporal,
    accuracy_confession, test_size. `labels_by_task[t]` is a list of label strings aligned with
    `lines`."""
    from transformers import AutoTokenizer, get_linear_schedule_with_warmup
    torch.manual_seed(seed)
    torch.set_num_threads(int(os.environ.get("TORCH_THREADS", "8")))

    # one stratified split shared by both heads (stratify on confession, the imbalanced task)
    idx = list(range(len(lines)))
    train_idx, test_idx = train_test_split(
        idx, test_size=test_frac, random_state=seed, stratify=labels_by_task['confession'])

    tokenizer = AutoTokenizer.from_pretrained(base_model)
    model = MultiTaskEncoder(base_model)
    model.train()

    def encode(indices):
        enc = tokenizer([lines[i] for i in indices], truncation=True, max_length=max_length,
                        padding=False)
        y = {t: [TASK_LABELS[t].index(labels_by_task[t][i]) for i in indices] for t in TASKS}
        return enc, y

    train_enc, train_y = encode(train_idx)
    weights = {t: _class_weights(train_y[t], len(TASK_LABELS[t])) for t in TASKS}
    loss_fns = {t: nn.CrossEntropyLoss(weight=weights[t]) for t in TASKS}

    order = list(range(len(train_idx)))
    optim = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.01)
    steps_per_epoch = (len(order) + batch_size - 1) // batch_size
    total_updates = (steps_per_epoch // grad_accum) * epochs
    scheduler = get_linear_schedule_with_warmup(
        optim, int(total_updates * warmup_ratio), max(total_updates, 1))

    optim.zero_grad()
    for epoch in range(epochs):
        np.random.RandomState(seed + epoch).shuffle(order)
        for step, start in enumerate(range(0, len(order), batch_size)):
            batch_ids = order[start:start + batch_size]
            batch = tokenizer.pad(
                {'input_ids': [train_enc['input_ids'][i] for i in batch_ids],
                 'attention_mask': [train_enc['attention_mask'][i] for i in batch_ids]},
                return_tensors='pt')
            logits = model(batch['input_ids'], batch['attention_mask'])
            loss = sum(loss_fns[t](logits[t],
                                   torch.tensor([train_y[t][i] for i in batch_ids]))
                       for t in TASKS)
            (loss / grad_accum).backward()
            if (step + 1) % grad_accum == 0:
                optim.step()
                scheduler.step()
                optim.zero_grad()
        print(f'[encoder] epoch {epoch} done', flush=True)

    # Evaluate both heads on the held-out test set
    model.eval()
    test_enc, test_y = encode(test_idx)
    preds = {t: [] for t in TASKS}
    with torch.no_grad():
        for start in range(0, len(test_idx), 32):
            ids = list(range(start, min(start + 32, len(test_idx))))
            batch = tokenizer.pad(
                {'input_ids': [test_enc['input_ids'][i] for i in ids],
                 'attention_mask': [test_enc['attention_mask'][i] for i in ids]},
                return_tensors='pt')
            logits = model(batch['input_ids'], batch['attention_mask'])
            for t in TASKS:
                preds[t].extend(logits[t].argmax(dim=1).tolist())

    metrics = {'test_size': len(test_idx)}
    for t in TASKS:
        acc = accuracy_score(test_y[t], preds[t])
        metrics[f'accuracy_{t}'] = float(acc)
        print(f'[encoder] {t} accuracy={acc:.4f}', flush=True)

    return model, tokenizer, metrics
