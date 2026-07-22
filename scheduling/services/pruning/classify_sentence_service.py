import threading

from django.db import transaction, IntegrityError

from scheduling.models.pruning_models import Classifier, Sentence, Pruning
from scheduling.services.pruning.classifier_target_service import get_target_enum
from scheduling.services.pruning.encoder_service import (get_prod_encoder,
                                                         get_prod_encoder_model)
from scheduling.services.pruning.train_classifier_service import set_label
from scheduling.utils.enum_utils import StringEnum
from scheduling.workflows.pruning.encoder import TorchHeadModel
from scheduling.workflows.pruning.extract.models import Source
from scheduling.workflows.pruning.extract_v2.models import Temporal, EventMention
from scheduling.workflows.pruning.train_and_predict import TensorFlowModel

_classifier = {}
_classifier_lock = threading.Lock()
_model = {}
_model_lock = threading.Lock()


def get_classifier(target: Classifier.Target
                   ) -> Classifier:
    global _classifier
    if _classifier.get(target, None) is None:
        with _classifier_lock:
            if _classifier.get(target, None) is None:
                print(f'Loading classifier for target {target}...')
                try:
                    classifier = Classifier.objects \
                        .filter(status=Classifier.Status.PROD, target=target) \
                        .latest('updated_at')
                except Classifier.DoesNotExist:
                    raise ValueError(f"No classifier in production for target {target}")

                # compatibility = trained on the current PROD encoder (DB row only, no HF load)
                assert classifier.encoder_id == get_prod_encoder_model().uuid, \
                    "Classifier and PROD encoder are not compatible"
                _classifier[target] = classifier

    return _classifier[target]


def get_model(classifier: Classifier):
    global _model

    target = Classifier.Target(classifier.target)
    if _model.get(target, None) is None:
        with _model_lock:
            if _model.get(target, None) is None:
                target_enum = get_target_enum(target)
                different_labels = target_enum.list_items()
                assert classifier.different_labels == different_labels, \
                    "Classifier and model are not compatible"
                if classifier.encoder_id is None:
                    tmp_model = TensorFlowModel[target_enum](different_labels)
                else:
                    tmp_model = TorchHeadModel[target_enum](different_labels)
                tmp_model.from_pickle(classifier.pickle)
                _model[target] = tmp_model

    return _model[target]


def classify_existing_sentence(sentence: Sentence, target: Classifier.Target
                               ) -> tuple[StringEnum, Classifier]:
    labels, classifier = classify_existing_sentences([sentence], target)

    return labels[0], classifier


def classify_existing_sentences(sentences: list[Sentence], target: Classifier.Target
                                ) -> tuple[list[StringEnum], Classifier]:
    # 1. Collect embeddings, reusing the stored one when still produced by the current encoder.
    embeddings = _encoder_embeddings(sentences)

    # 2. Get classifier + model
    classifier = get_classifier(target)
    model = get_model(classifier)

    # 3. Predict labels
    labels = model.predict(embeddings)

    return labels, classifier


def _encoder_embeddings(sentences: list[Sentence]) -> list:
    """Reuse each sentence's stored encoder_embedding; recompute (loading the encoder from HF) for
    any sentence not embedded by the current PROD encoder. A recomputed embedding is written back
    onto the sentence object so that callers which save it (reclassify_sentences, get_ml_label)
    persist the re-embedding lazily; pure inference just uses it transiently."""
    prod_encoder = get_prod_encoder_model()
    finetuned = None
    embeddings = []
    for sentence in sentences:
        if sentence.encoder_id == prod_encoder.uuid and sentence.encoder_embedding is not None:
            embeddings.append(sentence.encoder_embedding)
        else:
            if finetuned is None:
                _, finetuned = get_prod_encoder()
            embedding = finetuned.embed(sentence.line)
            sentence.encoder = prod_encoder
            sentence.encoder_embedding = embedding
            embeddings.append(embedding)
    return embeddings


def get_ml_label(sentence: Sentence, target: Classifier.Target) -> StringEnum:
    classifier = get_classifier(target)

    assert target == classifier.target, \
        f"Target {target} does not match classifier target {classifier.target}"

    if target == Classifier.Target.TEMPORAL:
        if sentence.temporal_classifier_id == classifier.uuid:
            return Temporal(sentence.ml_temporal)
    elif target == Classifier.Target.CONFESSION:
        if sentence.confession_new_classifier_id == classifier.uuid:
            return EventMention(sentence.ml_confession)
    else:
        raise NotImplementedError(f'Target {target} is not supported for label extraction')

    ml_label, _ = classify_existing_sentence(sentence, target)
    set_label(sentence, ml_label, classifier)
    sentence.save()

    return ml_label


def get_sentences_with_wrong_classifier(target: Classifier.Target) -> list[Sentence]:
    classifier = get_classifier(target)

    sentence_query = Sentence.objects

    if target == Classifier.Target.TEMPORAL:
        sentence_query = sentence_query.exclude(temporal_classifier=classifier)
    if target == Classifier.Target.CONFESSION:
        sentence_query = sentence_query.exclude(confession_new_classifier=classifier)

    return sentence_query.all()


def classify_and_create_sentence(stringified_line: str,
                                 pruning: Pruning) -> Sentence:
    # v2: fine-tuned encoder embedding (shared by temporal + confession)
    prod_encoder, finetuned = get_prod_encoder()
    encoder_embedding = finetuned.embed(stringified_line)

    sentence = Sentence(
        line=stringified_line,
        source=Source.ML,
        updated_on_pruning=pruning,
        updated_by=None,
        encoder=prod_encoder,
        encoder_embedding=encoder_embedding,
    )

    # V2 labels (reuse the just-computed encoder_embedding stored on the sentence)
    ml_temporal, temporal_classifier = classify_existing_sentence(sentence,
                                                                  Classifier.Target.TEMPORAL)
    set_label(sentence, ml_temporal, temporal_classifier)
    ml_confession, confession_classifier = classify_existing_sentence(
        sentence, Classifier.Target.CONFESSION)
    set_label(sentence, ml_confession, confession_classifier)

    try:
        # In the meantime, a sentence with the same line could have been created
        return Sentence.objects.get(line=stringified_line)
    except Sentence.DoesNotExist:
        try:
            with transaction.atomic():
                sentence.save()

            return sentence
        except IntegrityError:
            return Sentence.objects.get(line=stringified_line)
