# Confessio — Design Chart

## Philosophy

**Quiet confidence.** Confessio helps users find a confession time the same way
Google Maps helps users find a coffee shop: the user should never think about
the interface. Every pixel earns its place by either pointing to information
(time, place, day) or getting out of the way.

Three non-negotiables shape every decision:

1. **Reassurance over flash.** This app tells people where they can confess.
   The interface must feel stable, predictable, and calm — a tool that works,
   not a toy that performs.
2. **Maps DNA preserved.** A bottom sheet, a pin on a map, a search bar at
   the top. We do not reinvent familiar patterns, we refine them.
3. **One hero color.** Deep blue (`#242e4c`) is the brand. Everything else —
   accents, neutrals, states — exists to support it, never compete with it.

The aesthetic goal: **modern, classy, reliable**. Think transit-board
legibility, not enterprise SaaS.

---

## Tokens

### Color

| Token                | Value      | Role                                            |
| -------------------- | ---------- | ----------------------------------------------- |
| `--color-deepblue`   | `#242e4c`  | Signature. Used for headers, selected pins, next-upcoming time pills, primary text on paper. |
| `--color-lightblue`  | `#005cdf`  | Accent. Unselected hour pin, focus halo on search. Used sparingly. |
| `--color-paper`      | `#f7f4ee`  | Warm off-white. Modal inner card, list tiles, comment bubbles. |
| `--color-hairline`   | `#e7e3db`  | 1px separators, tile borders, divide rules on paper. |
| `--color-ink`        | `#1b2236`  | Body text on paper surfaces — slightly warmer than pure black. |

**Why warm neutrals?** Pure white reads clinical. `#f7f4ee` gives surfaces a
paper-like warmth without looking sepia — the classy/reassuring tone the design
is after. Pure black text on warm paper clashes subtly; `#1b2236` (deepblue
shifted toward black) keeps the warmth coherent.

**Opacity usage.** On the dark-blue modal canvas, secondary content uses
`text-white/65` and `/75` rather than new grays. On paper, `text-deepblue/55`
and `/60` handle the same role. Keeping secondary text as tinted variants of
the primary palette is what holds the interface together visually.

### Typography

**DM Sans** (400, 500, 600, 700) — the single UI font. Geometric, confident,
warmer than Inter or Geist. Tightened tracking (`-0.01em`) on large headings.

**No display font, no monospace.** We tried JetBrains Mono and DM Mono for
times to get a "transit board" feel. Both had distracting zero glyphs
(dotted/slashed), which felt technical. We landed on DM Sans with
`tabular-nums` — equal-width digits without the coder-font vibe. All times
use the `.tabular` class (`font-variant-numeric: tabular-nums;
font-feature-settings: "tnum" 1;`). Numbers still align in columns, but the
font feels continuous with the rest of the UI.

### Spacing / Radius

Three radii, one rule per layer:

- `rounded-full` — pills and circular buttons (time pills, close X, votes capsule, search pill)
- `rounded-2xl` (16px) — **outer surfaces**: modal sheet, list tiles, search dropdown
- `rounded-xl` (12px) — **inner surfaces**: inner paper card in modal, comment bubbles; also day tabs' top (`rounded-t-xl`, matches card below)

Rule: *outer 16, inner 12, interactive full.* We previously had `rounded-3xl`
(24px) on the modal and search, plus `rounded-2xl` nested inside — four
visible radii at once made the UI feel marshmallowy. Tightening each step
down pulls the interface toward "reliable record" and away from
"friendly pillow".

Shadows follow one rule: **one shadow, never two.** A doubled shadow looks
busy; a single soft drop shadow reads as reliable depth. Values are clamped
to low opacity (≤ 0.32) and short spread — enough to suggest elevation without
creating visual noise.

---

## Components

### Search Input (top of map)

- Single white pill with a 1px `--color-hairline` border and a very soft drop
  shadow `0 4px 14px -4px rgba(36,46,76,0.14)`.
- Focus ring: `0 0 0 3px rgba(0,92,223,0.18)` — lightblue at low opacity. The
  halo is subtle but unmistakable; it's the "yes, I'm listening" signal.
- Logo on the left doubles as a navigation entry point; Google-Maps-style.
- Results list sits under the pill on a shared paper-colored surface, no hard
  border between them — feels like the pill "dropped" the results.

**Why not a new shape?** The pill is the single most recognizable search
pattern on mobile maps. Changing it would cost familiarity for no gain.

### Leaflet Pins

Three pin types, unified visual language:

| Type                  | Unselected                          | Selected                                     |
| --------------------- | ----------------------------------- | -------------------------------------------- |
| **Hour pill**         | Lightblue bg, tabular time, soft shadow, no border. Triangle tail in matching color. | Deepblue bg, larger (58×28 vs 50×24), stronger shadow. |
| **Empty dot**         | 10px muted blue dot with white border + soft shadow. | 18px deepblue dot, white border, deeper shadow. |
| **Aggregation count** | 28px deepblue circle, white border, tabular count, soft shadow. | — |

**Why no halo?** We tried a 4px outer halo ring on selected pins. It read as
UI chrome — a second shape competing for attention. Removed. Selection is
communicated by size + color alone, exactly like Google Maps.

**Why no hover animation?** We tried `translateY(-1px)` on hover. The pill's
`::after` triangle tail didn't inherit the transform because it wasn't
positioned relative to the pill (Leaflet wraps pins in its own positioned
container). Rather than fight the CSS, we added `position: relative` to the
pill and dropped the hover animation entirely — still reassuring.

**Why no white border on the hour pill?** We tried a 1.5px white border + dual
shadow. Together they were too much visual armor for a ~50px pill. Dropping
the border and keeping only the shadow reads cleaner on map tiles.

### Modal Sheet — Church Card

The modal is **deep-blue by default**, paper-colored where we need focus.
This inversion is intentional: the card itself is the hero, so its interior
(the schedule) gets the warm paper surface.

**Header.** Church name at 22px/600 with tight leading. Address directly below
in `white/70` with a small `NavigationArrow` icon that hints at the Google
Maps directions link. Close button is a white/10 circle — present but not
loud.

**Day tabs.** A classic paper-tab metaphor, where the selected tab "fuses"
with the card below via two 8×8 radial-gradient cutouts at the bottom
corners. Previously these cutouts were `<span>` elements conditionally
rendered — they popped in/out with no transition. Moved to `::before` /
`::after` pseudo-elements always in the DOM, with `opacity: 0 → 1` on
`.day-tab-selected` and a 180ms ease. On tab change, the old cutouts fade
out while the new ones fade in.

**Inner card.** `bg-paper` with `divide-y divide-hairline` between events.
Each event row is a centered deepblue time pill (tabular) plus muted source
text below. The whole thing has a single low-opacity shadow — sits on the
dark canvas like a physical receipt.

**Feedback control.** A short question — *"Ces informations sont-elles à
jour ?"* — over two labeled pills: **Oui** (emerald thumb glyph + upvote count)
and **Erreur** (rose thumb glyph + downvote count). Pills are `bg-white/7` with
a `white/14` border, ≥44px tall; the active one tints to its sentiment
(`emerald-300/12` / `rose-300/12` bg, matching border). The count sits at
`white/55` beside each label as quiet social proof.

We previously used a bare icon-only vote capsule ("readable from a distance, no
labels needed"). It tested badly: a thumb next to a number read as a *scoreboard
to look at*, not a *control to tap* — users couldn't find how to report an
error. The fix is framing it as a **question with a verb**: that converts the
widget from output to input, which is the affordance a mobile control needs (no
hover to fall back on). This is a deliberate, scoped exception to the icon-only
preference — feedback is the one place the interface must actively *ask*.

**Comment bubbles.** Paper-colored on the dark canvas, deepblue text. Reads
as "a letter" rather than a chat DM — editorial tone matching the subject
matter.

### Modal Sheet — Church List (tiles)

**Paper tile** on the dark canvas, 1px `--color-hairline` border, no default
shadow. Hover/press adds a subtle drop shadow. The tile holds:

- Name (17px/600, deepblue, tight tracking)
- Address (12.5px, `deepblue/55`)
- **Schedule area**, two modes:

**Single-event mode** (total events === 1): the stacked day-label + time pill
chip sits to the right of the church name, inline with the header. A lone
pill at the bottom of a tile looked sparse and unconfident; right-aligning
it with the title keeps tile density honest and makes the day label
immediately present.

**Multi-event mode**: a horizontally scrolling rail of stacked chips, one
per event. If a day has two events, the day label repeats above each
pill — **no grouping**. Grouping looked visually clever but made it harder
to scan. Repetition is honest and works.

The very first chip (the next upcoming time) is filled deepblue; later chips
are outlined white with a hairline border. One highlight per tile — any more
would dilute the signal.

---

## What we rejected, and why

| Idea                                     | Why we dropped it                                              |
| ---------------------------------------- | -------------------------------------------------------------- |
| Monospace font for times                 | JetBrains/DM Mono zeros (dotted/slashed) felt technical. DM Sans with `tabular-nums` achieves alignment without the coder vibe. |
| Halo ring on selected pins               | Read as UI chrome. Size + color are enough signal.             |
| Hover `translateY` on hour pins          | `::after` tail didn't track the transform cleanly; looked janky. |
| Compact single-line inline chip          | Lost the day context in filter mode; users found it confusing. |
| Flatten filter-mode to show all day events unlabeled | Users needed the day label to stay oriented — filter or no filter. |
| Pseudo-corner cutouts as `<span>`        | Conditionally rendered → no opacity transition possible on mount/unmount. |

---

## Rules for future additions

1. **If in doubt, use deepblue.** Any new primary surface defaults to
   deepblue; any new content surface defaults to paper.
2. **Numbers are tabular.** If you render a time, date number, count, or any
   tabular data, apply `.tabular`.
3. **One shadow per element.** If you need more emphasis, don't stack
   shadows — change size or color first.
4. **Never introduce a new gray.** Use an opacity variant of deepblue
   (on paper) or white (on deepblue).
5. **Transitions are 150–200ms, ease.** Don't use bouncy easings. Don't
   transition transforms on map pins — Leaflet fights you.
6. **Match Google Maps where it matters.** Search pill at top, bottom sheet
   on mobile, tap-to-select pin, card slides up from bottom. Deviate only
   with explicit reason.
7. **External source attributions may use the source's brand color**, scoped
   strictly to the icon glyph and pill outline. Never on backgrounds, body
   text, or other Confessio chrome — the color is *attribution*, not styling.
   Today: OClocher uses `#609E2E` on a transparent outlined pill (see
   `ChurchCard.tsx`).
8. **State colors are a sanctioned, narrow exception to rule #4.** Feedback
   thumbs already use emerald/rose. The **holiday notice** adds a warm amber
   (`--color-warn-amber` `#92500c` on `--color-warn-amber-bg` `#fbf1df`,
   harmonized with paper) for the "Horaires susceptibles de changer pendant
   {la période}" line at the top of the schedule card (the period is named —
   e.g. les vacances scolaires, l'été, la Semaine sainte) — a deliberate nod to
   Google Maps' "Hours might differ" (rule #6). Amber is scoped to that one
   notice; don't reuse it as a general accent.
