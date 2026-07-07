# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.2] - 2026-07-07

### Changed

- Deploy as a Docker container instead of Vercel: add a multi-stage
  `Dockerfile` (Next.js standalone output) and a `docker-compose.yml` with a
  cron sidecar that replaces the Vercel cron, hitting
  `/api/revalidate-dioceses` daily at 01:00. Removed `vercel.json`.

## [1.0.1] - 2026-07-07

### Changed

- Date filter rail: tapping the already-selected day chip now clears the
  filter back to "Toutes les dates".
- Results sheet heading now reflects the selected date ("Horaires de
  confession aujourd'hui" / "demain" / "mardi 4 août") instead of the fixed
  "proches de vous"; falls back to "Horaires de confession" when no date is
  selected.
- Map marker pins for confessions 7+ days out now show a numeric date
  ("02/09") instead of a month name ("2 septembre") for clarity.

## [1.0.0] - 2026-07-03

### Added

- Date filter rail: a horizontal, scrollable day-chip selector
  ("Toutes les dates", "Aujourd'hui", "Demain", then 30 days) replaces the
  native `<input type="date">` in the results sheet.
- Map tile-loading shimmer that covers the map background until MapTiler
  fires its first `load`, then fades out (respects reduced-motion). Helps low-end device understand loading state
- Contextual church-marker labels: pins show the time when a date filter is
  active or the confession is today, otherwise "Demain", a weekday + day
  ("Sam. 15"), or a date ("14 juil.") depending on how far away it is.
- App version surfaced in the navigation modal and at `/api/health`.
- Self-hosting deploy scripts (`scripts/deploy.sh`, `scripts/poll.sh`).

### Fixed

- iOS date filter is now usable: the native date input (whose clear button
  is unreliable on iOS) is replaced by the tappable date-chip rail.
- iOS keyboard no longer hides content: a `useKeyboardOverlap` hook (backed by
  the VisualViewport API) pads the search results list and the church
  feedback box, and expands/scrolls the bottom sheet so the focused field
  stays above the keyboard.
- iOS Safari no longer force-zooms into the search box and feedback textarea
  (mobile font-size raised to 16px).
- Map marker pills size to their content instead of a fixed width, so longer
  labels ("Demain", "Sam. 15") no longer clip.

### Changed

- Double-tap-to-zoom disabled (`touch-action: manipulation`) for an app-like
  feel; pinch-to-zoom preserved.
- Tightened the default initial map bounds around Paris.
- Explicit white color on the navigation "Confessio" title.
- Canonical site URL centralized in `SITE_URL` and pointed at `confessio.fr`
  (overridable via `NEXT_PUBLIC_SITE_URL`).
- Node version pinned via `.nvmrc` (22); CI reads it.

## [0.1.0]

- Initial release.
