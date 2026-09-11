# Mobile pre-release checklist

| | |
|--|--|
| Date | YYYY-MM-DD |
| Tester | |
| Branch / commit | |
| Target URL | https://new.confessio.fr |

Walk through both runs on the listed device. Each run takes ~10 minutes.
Mark each step `✅`, `❌` (with a one-line note), or `N/A`.

---

## Run A — iPhone / iOS Safari

**Reference device:** iPhone 14 or newer, iOS 17+, Safari (private window OK).
**Why:** WebKit + iOS gesture nav + safe-area insets are the most likely
source of finicky bugs.

### Cold load & layout
- [ ] Open the home URL in a fresh tab. Map tiles render within ~3s, no white flash.
- [ ] No content is hidden behind the notch or the home indicator.
- [ ] Address bar is visible at first; scrolling the bottom sheet up causes it to collapse without the layout jumping (no `100vh` / `100dvh` pop).
- [ ] Rotate to landscape and back to portrait — layout adapts cleanly, no overlap.

### Map & search
- [ ] Pinch-zoom and two-finger pan work; the page itself doesn't pan.
- [ ] Tap the search input. Virtual keyboard opens; the search input stays visible (not hidden under the keyboard).
- [ ] Type a city (e.g. "Lyon"). Suggestions appear within ~500ms of stopping typing.
- [ ] Tap a suggestion → map pans / zooms to the result.
- [ ] Dismiss keyboard (tap outside or "Done"). Bottom sheet position is unaffected.

### Bottom sheet (the finicky one)
- [ ] Tap a church marker → bottom sheet opens at the **middle** snap point.
- [ ] Drag the handle up to the **top** snap point. The content area inside the sheet scrolls (not the page).
- [ ] At the top snap, scroll the content all the way to the bottom — overscroll bounce is contained inside the sheet, doesn't drag the map.
- [ ] At the top snap, scroll back up; the sheet doesn't snap down accidentally.
- [ ] Drag the handle down past the middle snap → sheet collapses.
- [ ] Tap a different marker while sheet is open — content updates, snap state stays at middle.
- [ ] Close the sheet (drag down to bottom / tap outside / X if any). No marker stays "selected" visually.

### Navigation modal
- [ ] Open the menu (burger / nav button). Modal overlays the map.
- [ ] Tap outside the modal — closes.
- [ ] Tap "Nous contacter" — leaves to confessio.fr/contact. Hit back: returns to the map at the same state (zoom, marker selection).

### Deep links / SEO routes
- [ ] Open `/diocese/paris` directly. Page resolves to the map zoomed/bounded on Paris within ~2s. Browser back works (does not loop).
- [ ] Open a `/church/<uuid>` URL directly. Page does not crash. (Currently bare; just verify no error screen.)
- [ ] Hit a non-existent slug, e.g. `/diocese/zzz-not-real`. App shows a 404, not a server error.

### Edge cases
- [ ] Toggle airplane mode briefly while on the map. Reconnect: app recovers (markers reload or state stays).
- [ ] Background the app for 1 minute, return: state is preserved, no white screen.

---

## Run B — Android / Chrome

**Reference device:** Pixel 7 / 8 or Samsung Galaxy S22+, current Chrome stable.
**Why:** Blink engine, Android virtual keyboard sizing, edge-swipe-back gesture, different scroll-chaining behaviour against the map.

### Cold load & layout
- [ ] Open the home URL fresh. Map tiles render within ~3s.
- [ ] On a device with a navigation bar (3-button), the bottom sheet bottom snap doesn't sit *under* the nav bar.
- [ ] On a gesture-nav device, the bottom of the sheet leaves room for the gesture indicator.
- [ ] Rotate landscape → portrait. Layout adapts.

### Map & search
- [ ] Pinch-zoom and two-finger pan work; the page itself doesn't scroll.
- [ ] Tap search input. Android keyboard opens; **the bottom sheet doesn't get pushed off-screen** (a real Android-specific bug pattern).
- [ ] Type "Lyon" → suggestions debounced.
- [ ] Tap a suggestion → map pans.
- [ ] Dismiss keyboard with the back button (system gesture). Sheet returns to its prior snap, no flicker.

### Bottom sheet
- [ ] Tap marker → sheet opens at middle snap.
- [ ] Drag up to top snap; inner content scrolls; outer page does not scroll under the sheet.
- [ ] At top snap, do a fast flick scroll inside the content. No "double scroll" — the map below should not move.
- [ ] Drag handle down → collapses cleanly.
- [ ] Tap a different marker → content updates, snap stays at middle.

### Navigation modal & system back
- [ ] Open menu modal. Press the **system back gesture** (edge swipe) — modal closes (or app navigates back to the map, depending on intent). It must not leave the user stranded on a blank screen.
- [ ] In the modal, tap "Nous contacter" → leaves to confessio.fr. System back returns to the map.

### Deep links / SEO routes
- [ ] Open `/diocese/paris` directly. Resolves to the map. Hit system back: behaviour is sane (does not infinite-redirect).
- [ ] Open a `/church/<uuid>` URL directly. Does not crash.
- [ ] Hit a non-existent slug, e.g. `/diocese/zzz-not-real`. 404 page, not a server error.

### Edge cases
- [ ] Toggle airplane mode briefly. Reconnect: app recovers.
- [ ] Pull-to-refresh from the top of the page — confirm Chrome's PTR doesn't fight with the sheet (either the sheet absorbs the gesture or PTR works cleanly).
- [ ] Background app for 1 minute, return: state preserved.

---

## Optional — quarterly extended run

Run roughly once every 3 months, or after any change to layout / sheet / map code:

- **iPad Safari** — verify the desktop layout vs mobile layout breakpoint behaves correctly. Tablet viewports often fall in a "neither" state.
- **Firefox Android** — Gecko is third-most-common on Android. Run the same checklist as Run B; flag anything Firefox-specific.
- **Older iPhone (SE 2nd gen, iOS 16)** — small viewport + older WebKit. Useful for catching layout overflow bugs.

---

## Reporting issues

For every `❌`:
1. Note OS / browser version exactly (Settings → About).
2. Screen-record if possible (iOS: Control Center; Android: built-in recorder).
3. File a Linear ticket with the recording, the reproduction steps from this checklist, and a link to the run file in `runs/`.
