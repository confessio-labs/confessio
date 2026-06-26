from core.management.abstract_command import AbstractCommand
from scheduling.services.pruning.encoder_service import push_staging_to_hf, DEFAULT_HF_REPO_ID


class Command(AbstractCommand):
    help = ("Developer-only (DEV). (Re)upload the locally-staged encoder artifacts (from the last "
            "train_encoder) to its HF repo. Use to retry a push that failed (e.g. transient "
            "network) without retraining.")

    def add_arguments(self, parser):
        parser.add_argument('--repo-id', default=DEFAULT_HF_REPO_ID,
                            help='private HF repo to push the staged encoder to')

    def handle(self, *args, **options):
        self.info(f'Uploading staged encoder artifacts to {options["repo_id"]}...')
        try:
            revision = push_staging_to_hf(options['repo_id'])
        except Exception as exc:
            self.error(f'Push failed ({exc}).')
            return
        self.success(f'Pushed to {options["repo_id"]}@{revision}.')
        self.warning(f'To go live: python manage.py promote_encoder '
                     f'--repo-id {options["repo_id"]} --revision {revision}')
