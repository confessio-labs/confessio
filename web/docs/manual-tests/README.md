# Manual tests

Automated tests cover the SEO contract (`pnpm test:seo`). Mobile gestures,
the bottom sheet and the map are verified by hand before each prod release.

## Cadence

Before every merge from `staging` to `main` (roughly monthly), walk through
`mobile-pre-release.md` on the two reference devices listed there.

If anything fails, either fix it before releasing or note it in the
release notes as a known regression. Don't silently skip steps — if a
step doesn't apply (e.g. a feature was removed), update the checklist.

## How to use

1. Copy `mobile-pre-release.md` to `runs/YYYY-MM-DD.md` (one per release).
2. Fill in tester name, app version, and date at the top.
3. Tick each box as you go. Note pass / fail / N/A and a short comment
   when something is off.
4. Commit the filled run to git so we have a release-by-release history
   of what was tested.

## Why these devices

The two reference devices are picked to cover the meaningful
behavioural split, not market share:

- **iOS Safari** — WebKit, iOS gesture nav, momentum scrolling,
  address-bar resize, safe-area insets (notch / home indicator). The
  bottom sheet drag and overscroll behave differently here than on
  Blink.
- **Android Chrome** — Blink, Android gesture nav / 3-button nav,
  virtual keyboard sizing, swipe-back from the screen edge, different
  scroll-chain behaviour against the map underneath.

Chrome on iOS uses WebKit under the hood, so iOS Safari covers it.
Firefox Android and iPad Safari are tested less often (see the
optional run in the checklist) — once a quarter is enough.
