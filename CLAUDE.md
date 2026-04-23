# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A static fan-made landing page for Curious Coffee (Ann Arbor, MI). Deployed on Vercel at `curious-coffee.vercel.app`. No build step, no bundler, no dependencies.

## Running the coffee card updater

```bash
# Update coffee cards from the live shop (run from repo root)
python3 update_coffees.py
```

The script uses only stdlib (`urllib`, `html.parser`, `re`) — no pip install needed locally. CI installs `requests` and `beautifulsoup4` but the script does not actually use them; those are leftover from a prior version.

To preview changes, open `index.html` directly in a browser.

## Architecture

**Everything lives in one file: `index.html` (~1.8 MB).** All CSS and JS are inline. There is no separate stylesheet or script file.

**`update_coffees.py`** scrapes `curious-coffee.com`, builds flip-card HTML, and injects it between two sentinel comments in `index.html`:

```
<!-- COFFEE_CARDS_START -->
  ... generated flip-wrap divs ...
<!-- COFFEE_CARDS_END -->
```

If either sentinel is missing, the script aborts rather than wiping the existing cards.

**GitHub Actions** (`.github/workflows/update-coffees.yml`) runs the scraper daily at 6pm EST and commits `index.html` only when it changes.

## Key config in `update_coffees.py`

| Variable | Purpose |
|---|---|
| `CATEGORY_MAP` | Maps product URL slugs to `"standard"` or `"premium"`. Everything not listed defaults to `"premium"`. Must be updated manually when new products launch. |
| `SHOW_INITIALLY` | Number of cards visible before "See All" button. Currently `8`. |
| `FACE_TOP_HASHES` / `FACE_TOP_LEFT_HASHES` | Wix image URL hash fragments that trigger non-default `object-position` on farm photos (to keep faces in frame). Add hashes when a new farm photo crops badly. |

## Card rendering

Cards are 3D CSS flip cards. Front: bag photo + tasting notes pills + price. Back: farm photo + description + buy link. Out-of-stock cards are sorted last and rendered with disabled buy buttons and an OOS badge. The `const SHOW=N;` JS constant in `index.html` is kept in sync with `SHOW_INITIALLY` by the scraper on each run.

**Flip interaction**: cards flip on click (not hover) on all devices. Clicking a link or button on the visible face passes through without toggling the flip. The JS handler is in `index.html` outside the touch-device block.

**Farm image positioning**: defaults to `object-position: top` so faces stay in frame. Override by adding the Wix image hash to `FACE_TOP_LEFT_HASHES` (top-left crop) or by detecting landscape dims (`w > h`) which forces `center`.

## Modifying the page

- **CSS/JS changes**: edit directly in `index.html` — there is no separate source file to keep in sync.
- **Adding a new product category**: add the slug to `CATEGORY_MAP` in `update_coffees.py`, then re-run the script.
- **Fixing a cropped farm photo**: find the Wix image hash (8 hex chars after `/media/`) and add it to `FACE_TOP_HASHES` or `FACE_TOP_LEFT_HASHES`.
- **Background video**: not committed to the repo. The `index.html` comment at the top references a Pexels video (`/video/coffee-beans.mp4`) that must be placed locally or via Vercel asset.
