from core.management.abstract_command import AbstractCommand
from scheduling.services.pruning.encoder_service import (create_encoder_from_hf, promote_encoder,
                                                         DEFAULT_HF_REPO_ID)


class Command(AbstractCommand):
    help = ("Developer-only. Register an encoder from its HF repo into THIS database and make it "
            "the official one: create the Encoder row + the two head Classifiers, significance-"
            "check vs the current PROD encoder, then flip PROD. Does NOT re-embed (that happens "
            "lazily via classify + reclassify_sentences). Restart inference processes afterwards.")

    def add_arguments(self, parser):
        parser.add_argument('--repo-id', default=DEFAULT_HF_REPO_ID,
                            help='private HF repo holding the fine-tuned encoder')
        parser.add_argument('--revision', default=None,
                            help='HF commit sha to pin (defaults to the repo head)')
        parser.add_argument('-f', '--force', action='store_true',
                            help='promote even if not significantly better than PROD')

    def handle(self, *args, **options):
        self.info(f'Registering encoder from {options["repo_id"]}'
                  f'{"@" + options["revision"] if options["revision"] else ""}...')
        encoder = create_encoder_from_hf(options['repo_id'], options['revision'])
        heads = {c.target: c for c in encoder.classifiers.all()}
        accuracies = ', '.join(f'{target}={head.accuracy:.4f} (test_size={head.test_size})'
                               for target, head in sorted(heads.items()))
        self.info(f'Created DRAFT encoder {encoder.uuid} with heads: {accuracies}.')

        promoted, message = promote_encoder(encoder, force=options['force'])
        if promoted:
            self.success(message)
            self.warning('Restart inference processes (web/worker) to load the new PROD encoder.')
        else:
            self.warning(message)
