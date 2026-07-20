# Confessio

## Design system

Before making any visual/UI change, read `docs/design.md`. It defines the
color tokens, typography, component patterns, and the rules that keep the
interface coherent (one hero color, tabular numbers, one shadow per element,
opacity variants instead of new grays, etc.).

When in doubt, default to the existing tokens in `src/app/globals.css`
(`--color-deepblue`, `--color-paper`, `--color-hairline`, `--color-ink`,
`--color-lightblue`) rather than introducing new values.

If a UI change contradicts a rule in `docs/design.md`, flag it and either
update the doc (if the rule should evolve) or revise the change.

## Testing

See `docs/testing.md` for the full workflow.

- Automated SEO smoke tests live in `tests/seo.spec.ts` and run via
  `pnpm test:seo` (full build + run) or `pnpm test:seo:only` (run only).
  Run them after any change to page metadata, `sitemap.ts`, the diocese
  or church routes, or anything in `src/lib/jsonld.ts`. Tests run on
  port **3100** to avoid colliding with `next dev`.
- Manual mobile QA before each prod release: copy
  `docs/manual-tests/mobile-pre-release.md` into
  `docs/manual-tests/runs/YYYY-MM-DD.md`, run both device passes,
  commit the filled file.
