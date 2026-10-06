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

Nothing else triggers a rebuild — not the clock, not a new signatory. Since
several things on the site are baked in at build time (signatory logos pulled
from Drive, Substack posts on News, and the HTML search engines read), a
scheduled job supplies the missing commit: `.github/workflows/nightly-rebuild.yml`
writes a fresh timestamp into `.rebuild-stamp` at 12:00 UTC and pushes it,
which Cloudflare sees as a change. It can also be run on demand from the
Actions tab, which is the easiest way to force a rebuild without editing
anything. It needs **Settings → Actions → General → Workflow permissions** set
to "Read and write" so the job can push. Note that GitHub suspends scheduled
workflows in a repository with no activity for 60 days, and emails the owner
when it does.

A build that can't read the signatories sheet now fails instead of falling
back to `data/signatories_live.csv`. A failed build deploys nothing and leaves
the current site up, which is the safe outcome; quietly publishing a months-old
snapshot would drop real signatories off the site with nothing appearing to go
wrong. The same applies if the sheet reads but nobody in it consents to being
listed, which means the columns or the consent question moved rather than that
everyone withdrew. `ALLOW_STALE_SIGNATORIES=1` opts back into the snapshot for
working offline — this repo's sandbox can't reach Google — and must never be
set in Cloudflare.

The site answers on `saunaforall.org`, with `www` 301-redirecting to it. The
old `*.workers.dev` address is switched off, so there is only ever one copy of
the site. `SITE_URL` in `build.py` is the single source for every absolute URL
-- canonical tags, Open Graph, the sitemap and robots.txt all derive from it.

## Content

Most copy lives in `build.py` as the source of truth. The exception is the
signatories directory, which comes from the live Charter questionnaire
Google Sheet at build time; if the sheet can't be reached the build fails
rather than publish a list it can't vouch for (see Deploys). The directory and
homepage tally also refresh at runtime from a feed worker, so new signatories
appear without a rebuild — logos, which are files rather than feed data, still
wait for the next build.

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

## One organisation, several signers

Everyone who signs for the same organisation shares one card, listed on its
"Signed by" line -- matched ignoring capitals, so "Fad saoil saunas" and "Fad
Saoil Saunas" group together. A card carries at most one quote. The first
person to share a commitment supplies it; anyone after them who also chose to
share theirs gets a card of their own, under the same organisation name, so
their words aren't dropped and no card doubles in length. People who only
added their name stay on the main card. A split card sorts by its own signer's
date, and doesn't add to the homepage signatory count -- it's the same
organisation.

The feed Worker only knows how to group, so the build passes its splits to the
page in `window.SIGNATORY_SPLITS` and the feed refresh re-applies them. Someone
who joins an organisation between deploys stays grouped until the next build.

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

Because the file is named after the card's title, renaming a signatory's
organisation -- or clearing it, which makes the card fall back to the person's
name -- orphans the stored logo: the page looks for a file under the new title
and finds none, so the card shows an initials badge until the next build
re-downloads the upload under the new name.

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
