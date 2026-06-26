from core.management.abstract_command import AbstractCommand
from scheduling.services.pruning.encoder_service import (train_and_stage_encoder,
                                                         push_staging_to_hf,
                                                         DEFAULT_BASE_MODEL, DEFAULT_HF_REPO_ID)


class Command(AbstractCommand):
    help = ("Developer-only (DEV). Jointly fine-tune the V2 encoder (camembert-large) + temporal "
            "& confession heads on the local DB, then push body + tokenizer + meta.json (with the "
            "head weights) to a private HF repo. NO database writes. Heavy (~5-6 GB, offline). "
            "Training is staged locally before the upload, so a failed push is retryable with "
            "push_encoder. Then run promote_encoder --repo-id ... on prod.")

    def add_arguments(self, parser):
        parser.add_argument('--repo-id', default=DEFAULT_HF_REPO_ID,
                            help='private HF repo to push the fine-tuned encoder to')
        parser.add_argument('--base-model', default=DEFAULT_BASE_MODEL,
                            help='HF base model to fine-tune')

    def handle(self, *args, **options):
        self.info(f'Fine-tuning encoder {options["base_model"]} (this is slow)...')
        metrics = train_and_stage_encoder(options['base_model'])
        self.success(f'Trained & staged locally: temporal={metrics["accuracy_temporal"]:.4f} '
                     f'confession={metrics["accuracy_confession"]:.4f} '
                     f'(test_size={metrics["test_size"]}).')

        self.info(f'Pushing to {options["repo_id"]}...')
        try:
            revision = push_staging_to_hf(options['repo_id'])
        except Exception as exc:
            self.error(f'HF push failed ({exc}). Training is SAFE (staged locally). Once '
                       f'connectivity is fixed, retry without retraining: '
                       f'python manage.py push_encoder --repo-id {options["repo_id"]}')
            return
        self.success(f'Pushed to {options["repo_id"]}@{revision}.')
        self.warning(f'To go live (run on prod, or locally to test): python manage.py '
                     f'promote_encoder --repo-id {options["repo_id"]} --revision {revision}')
