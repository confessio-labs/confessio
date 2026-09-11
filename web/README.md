# Confessio

A modern web application for finding Catholic churches and confession times, designed to replace the current [confessio.fr](https://confessio.fr) instance.

## Project Priorities

- **User-centric design**: Simple, intuitive interface that puts users first
- **Server-side rendering**: Full SSR for optimal SEO and performance
- **Simplicity**: Focus on essential features with minimal complexity

## Tech Stack

- Next.js 15 (App Router)
- React 19
- TypeScript
- Tailwind CSS
- TanStack Query
- Leaflet/MapTiler for interactive maps

## Development

```bash
# Install dependencies
pnpm install

# Run development server
pnpm dev
```

Open [http://localhost:3000](http://localhost:3000) to view the app.

### Additional Commands

```bash
# Build for production
pnpm build

# Start production server
pnpm start

# Lint code
pnpm lint

# Format code
pnpm format

# Pull latest API types from production
pnpm pull-types
```

## Deployment

The application can be deployed on [Vercel](https://vercel.com) or any platform supporting Next.js applications.

For Vercel deployment:
1. Push your code to a Git repository
2. Import the project in Vercel
3. Configure environment variables if needed
4. Deploy

See [Next.js deployment documentation](https://nextjs.org/docs/app/building-your-application/deploying) for other deployment options.

## Releasing

Version is single-sourced from `package.json` and exposed to the UI and
`/api/health` at build time (`NEXT_PUBLIC_APP_VERSION`).

To cut a release:

1. Add the changes under `## [Unreleased]` in `CHANGELOG.md`, then rename that
   heading to the new version.
2. `pnpm version <patch|minor|major>` — bumps `package.json` and creates the
   matching `vX.Y.Z` git tag.
3. `git push && git push --tags`.

On `confessio.fr` the poller (`scripts/poll.sh`) picks up the new commit on
`main` and runs `scripts/deploy.sh`.

## API Documentation

Backend API documentation is available at [https://confessio.fr/front/api/docs#/](https://confessio.fr/front/api/docs#/).

## Preview

The project is deployed for preview at [confessio-front.vercel.app](https://confessio-front.vercel.app).

## Design

Design files are hosted on [https://penpot.pcdhebrail.ovh](https://penpot.pcdhebrail.ovh) (ping me to get access).

## Development Status

Current development progress and planned features are tracked in [TODO.md](./TODO.md).
