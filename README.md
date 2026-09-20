# Sauna for All

Marketing site for Sauna for All and the Public Sauna-Bathing Charter.
Live at https://saunaforall.org

## How it works

A small static-site generator. `build.py` writes the eight HTML pages from
Python templates, then `prepare_deploy.py` inlines the CSS and JS into each
page and copies the referenced images and files into `dist/`.

```
python3 build.py          # regenerates the .html pages
python3 prepare_deploy.py # writes the deployable dist/ folder
```

Standard library only — nothing to install. `dist/` is generated, not
committed.

## Deploys

Cloudflare Workers Builds is connected to this repo. A commit to `main`
rebuilds and redeploys automatically; `wrangler.toml` points it at `dist/`.
No manual upload step.

The site answers on `saunaforall.org`, with `www` 301-redirecting to it. The
old `*.workers.dev` address is switched off, so there is only ever one copy of
the site. `SITE_URL` in `build.py` is the single source for every absolute URL
-- canonical tags, Open Graph, the sitemap and robots.txt all derive from it.

## Content

Most copy lives in `build.py` as the source of truth. The exception is the
signatories directory, which comes from the live Charter questionnaire
Google Sheet at build time, with `data/signatories_live.csv` as a committed
fallback for when the sheet can't be reached — so a build never publishes an
empty directory. The directory and homepage tally also refresh at runtime
from a feed worker, so new signatories appear without a rebuild.

## News

The News page is built from the Substack RSS feed
(`saunaforall.substack.com/feed`) at build time: each post becomes a card with
its cover image, title, date and an excerpt, linking to the post on Substack.
The grid is three columns on desktop, two on tablet, one on mobile.

Fetched during the build rather than from the browser, because Substack's feed
sends no CORS headers — a page-load fetch would need a proxy worker deployed
and kept running. Baking the posts in means no extra infrastructure, the page
works without JavaScript, and a slow Substack can't leave a half-rendered grid.
The trade-off is that new posts appear on the next deploy rather than instantly.

If the feed can't be reached the build says so and the page falls back to its
"News is on its way" message, and if a post's cover image fails to load the card
shows the branded placeholder instead of a gap.

## Signatory order and paging

The directory is ordered by when each signatory actually signed — earliest
first, read from the response sheet's Timestamp column (A). An organisation
takes the date of whoever signed for it first, so adding a second person to an
existing organisation never moves its card. Twelve cards show at a time behind
a "Show more" button (`SIGNATORY_PAGE_SIZE` in `build.py`); filtering or
searching starts the count again from the top, so the button always reflects
the set actually being looked at.

The live feed Worker returns signatories with no date attached, and
`js/signatories-feed.js` replaces the whole grid — so left alone, the feed's
order would override the build's. Instead the build writes the order it worked
out into `window.SIGNATORY_ORDER` as normalised names, and the feed refresh
sorts itself into that order. Anyone the feed knows about who wasn't in the
last build has signed since, so they sort to the end, which is where earliest-
first puts them anyway. Names are matched with case and punctuation stripped,
because the sheet and the feed don't always agree on them — `_order_key()` in
`build.py` and `orderKey()` in the feed script have to stay in step.

## Signatory logos

The questionnaire's logo question ("upload your organisation's logo, or a
headshot if signing as an individual") writes uploads to its own Drive folder.
Each build reads the file id from the sheet, downloads the image through
Drive's thumbnail endpoint, and writes it to `images/signatories/<slug>.<ext>`,
where the page picks it up. Signatories without an upload get an initials
badge instead.

This works with no credentials because that folder is shared as **anyone with
the link can view**, and new uploads inherit that sharing — so a signatory who
uploads a logo has it appear on the next deploy with nobody intervening. Forms
gives every file-upload question its own folder, so this one holds only logos
and headshots; reference letters are in a separate, private folder and stay
that way.

If the fetch fails, the build says so per signatory and that card falls back to
an initials badge until the next build — nothing breaks, and nothing fails
silently. Downloads are gitignored: Drive is the source of truth. To override
one by hand, `git add -f images/signatories/<slug>.png`; a file already present
is never overwritten.

## Layout

| Path | What it is |
|---|---|
| `build.py` | page templates, copy, and the signatories loader |
| `prepare_deploy.py` | inlines assets and assembles `dist/` |
| `css/`, `js/` | source stylesheet and scripts (inlined at deploy time) |
| `images/`, `files/` | photos, headshots, principle icons, Charter PDF |
| `data/` | signatories snapshot and notes on refreshing it |
| `workers/` | the separate Substack feed worker |

`CMS_SETUP.md`, `DOMAIN_CUTOVER.md` and `PUNCH_LIST.md` cover the remaining
open work.
