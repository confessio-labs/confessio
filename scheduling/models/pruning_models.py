from django.contrib.postgres.fields import ArrayField
from django.db import models
from pgvector.django import VectorField
from simple_history.models import HistoricalRecords

from core.models.base_models import TimeStampMixin
from registry.models import Diocese
from registry.models.base_moderation_models import ModerationMixin
from scheduling.workflows.pruning.extract_v2.models import Temporal, EventMention


class Pruning(TimeStampMixin):
    # We can not set unique=True because size can exceed index limits
    extracted_html = models.TextField(editable=False)
    extracted_html_hash = models.CharField(max_length=32, unique=True, editable=False)
    v2_indices = ArrayField(models.PositiveSmallIntegerField(), null=True)
    human_indices = ArrayField(models.PositiveSmallIntegerField(), null=True)

    history = HistoricalRecords()

    def get_pruned_indices(self):
        return self.human_indices if self.human_indices is not None else self.v2_indices

    def get_diocese(self) -> Diocese | None:
        if not self.scrapings.exists():
            return None

        return self.scrapings.first().website.get_diocese()


class Sentence(TimeStampMixin):
    line = models.TextField(null=False, unique=True)
    prunings = models.ManyToManyField('Pruning', related_name='sentences')
    updated_by = models.ForeignKey('auth.User', on_delete=models.SET_NULL, null=True)
    updated_on_pruning = models.ForeignKey('Pruning', on_delete=models.SET_NULL, null=True)
    # v2 (temporal/confession) uses the fine-tuned Encoder embedding
    encoder = models.ForeignKey('Encoder', on_delete=models.SET_NULL, related_name='sentences',
                                null=True)
    encoder_embedding = VectorField(dimensions=1024)
    # v2
    ml_temporal = models.CharField(max_length=5, choices=Temporal.choices())
    human_temporal = models.CharField(max_length=5, choices=Temporal.choices(), null=True)
    temporal_classifier = models.ForeignKey('Classifier', on_delete=models.SET_NULL,
                                            related_name='temporal_sentences', null=True)

    ml_confession = models.CharField(max_length=7, choices=EventMention.choices())
    human_confession = models.CharField(max_length=7, choices=EventMention.choices(), null=True)
    confession_new_classifier = models.ForeignKey('Classifier', on_delete=models.SET_NULL,
                                                  related_name='confession_new_sentences',
                                                  null=True)
    history = HistoricalRecords()


class Encoder(TimeStampMixin):
    """A fine-tuned sentence encoder (camembert-large) producing the embedding consumed by the
    V2 temporal/confession heads (Classifier). Weights live in a private Hugging Face repo.
    Trained and promoted only via developer commands (train_encoder / promote_encoder)."""

    class Status(models.TextChoices):
        DRAFT = "draft"
        PROD = "prod"

    status = models.CharField(max_length=5, choices=Status)
    base_model = models.CharField(max_length=100)  # e.g. "camembert/camembert-large"
    hf_repo_id = models.CharField(max_length=200)  # private HF repo holding the fine-tuned weights
    hf_revision = models.CharField(max_length=100, null=True)  # commit sha to pin the weights
    dimensions = models.PositiveSmallIntegerField()  # embedding size, e.g. 1024

    # Per-task accuracy lives on the head Classifiers (related_name='classifiers'), not here:
    # an accuracy is the performance of an (encoder, head) pair, and the promotion gate reads it
    # from the linked heads.
    notes = models.TextField(null=True, blank=True)
    history = HistoricalRecords()


class Classifier(TimeStampMixin):
    class Status(models.TextChoices):
        DRAFT = "draft"
        PROD = "prod"

    class Target(models.TextChoices):
        # V1
        ACTION = "action"
        # V2
        TEMPORAL = "temporal"
        CONFESSION = "confession"

    transformer_name = models.CharField(max_length=100)
    # v2 heads (temporal/confession) reference the Encoder that produces their input embedding;
    # null for v1 action heads, which keep the frozen sentence-transformer (transformer_name).
    encoder = models.ForeignKey('Encoder', on_delete=models.SET_NULL,
                                related_name='classifiers', null=True)
    status = models.CharField(max_length=5, choices=Status)
    target = models.CharField(max_length=10, choices=Target)
    different_labels = models.JSONField()
    pickle = models.CharField()
    accuracy = models.FloatField()
    test_size = models.PositiveSmallIntegerField()
    history = HistoricalRecords()


class PruningModeration(ModerationMixin):
    class Category(models.TextChoices):
        NEW_PRUNED_HTML = "new_pruned_html"
        V2_DIFF_HUMAN = "v2_diff_human"
        V2_DIFF_V1 = "v2_diff_v1"

    resource = 'pruning'
    diocese = models.ForeignKey('registry.Diocese', on_delete=models.CASCADE,
                                related_name=f'{resource}_moderations', null=True)
    history = HistoricalRecords()
    pruning = models.ForeignKey('Pruning', on_delete=models.CASCADE, related_name='moderations')
    category = models.CharField(max_length=16, choices=Category)

    class Meta:
        unique_together = ('pruning', 'category')

    def delete_on_validate(self) -> bool:
        # we keep PruningModeration even if pruned_indices has changed
        # in order to keep track of which pruned_indices has been moderated
        return False


class SentenceModeration(ModerationMixin):
    class Category(models.TextChoices):
        V2_OUTLIER = "v2_outlier"

    resource = 'sentence'
    diocese = models.ForeignKey('registry.Diocese', on_delete=models.CASCADE,
                                related_name=f'{resource}_moderations', null=True)
    history = HistoricalRecords()
    sentence = models.ForeignKey('Sentence', on_delete=models.CASCADE, related_name='moderations')
    category = models.CharField(max_length=20, choices=Category)

    class Meta:
        unique_together = ('sentence', 'category')

    def delete_on_validate(self) -> bool:
        return False
