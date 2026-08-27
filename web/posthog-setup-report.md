# PostHog post-wizard report

The wizard has completed a deep integration of PostHog into Confessio. PostHog is initialized via `instrumentation-client.ts` (Next.js 15.3+ approach) with EU hosting, a reverse proxy through `/ingest`, automatic exception capture, and debug mode in development. Ten events were instrumented across three client components covering the full user journey: search, church discovery, engagement, navigation, and feedback.

| Event | Description | File |
|---|---|---|
| `church_viewed` | Fired when a user opens a church detail modal to view confession schedules | `src/components/ChurchCard.tsx` |
| `search_performed` | Fired when a user types a search query to find a church or municipality | `src/components/SearchInput.tsx` |
| `search_result_selected` | Fired when a user selects a result from the autocomplete search list | `src/components/SearchInput.tsx` |
| `directions_opened` | Fired when a user clicks the church address to open Google Maps directions | `src/components/ChurchCard.tsx` |
| `parish_website_clicked` | Fired when a user clicks the link to visit the parish website | `src/components/ChurchCard.tsx` |
| `contribution_link_clicked` | Fired when a user clicks the link to complete/correct church schedules | `src/components/ChurchCard.tsx` |
| `church_upvoted` | Fired when a user clicks the thumbs up button on a church | `src/components/ChurchCard.tsx` |
| `church_downvoted` | Fired when a user clicks the thumbs down button on a church | `src/components/ChurchCard.tsx` |
| `navigation_modal_opened` | Fired when a user opens the navigation/about modal via the logo button | `src/components/SearchInput.tsx` |
| `center_on_me_clicked` | Fired when a user clicks the geolocation button to center the map on their position | `src/app/@map/default.tsx` |

## Next steps

We've built some insights and a dashboard for you to keep an eye on user behavior, based on the events we just instrumented:

- **Dashboard — Analytics basics**: https://eu.posthog.com/project/155129/dashboard/608654
- **Church Views Over Time**: https://eu.posthog.com/project/155129/insights/XdQ0KAwO
- **User Engagement: Search, Views & External Links**: https://eu.posthog.com/project/155129/insights/3I6zmohR
- **Upvotes vs Downvotes**: https://eu.posthog.com/project/155129/insights/FZPoBCHZ
- **Search-to-Church-View Funnel**: https://eu.posthog.com/project/155129/insights/hxnzUE23
- **Church View to Contribution Funnel**: https://eu.posthog.com/project/155129/insights/mX5eQyHF

### Agent skill

We've left an agent skill folder in your project. You can use this context for further agent development when using Claude Code. This will help ensure the model provides the most up-to-date approaches for integrating PostHog.
