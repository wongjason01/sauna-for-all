# Punch list: what's left before launch

The rebuild against SPEC.md is complete and pushed to GitHub (`main`): all eight pages
(Home, About, Charter, Signatories, News, Resources, Contact, FAQs) are built, verified
against the Section 9 "Done" checklist, and free of the copy/formatting issues that
checklist calls out (no em dashes, British spelling, no duplicate hero image, "in
practice"/"Draft" and the old quotes placeholder removed, and so on).

What's below is everything that still needs a person -- Becky's content, or an account
this project doesn't have access to -- before the site can fully launch.

## 0. Most urgent: the live site hasn't been updated yet

Every change in this rebuild lives on GitHub. **None of it has reached the live
Cloudflare Worker** -- the deployment step is a manual "upload static files" action in
the Cloudflare dashboard that needs a logged-in account, so it couldn't be done from
here. Right now, whoever visits the live `workers.dev` address (or saunaforall.org, once
that's connected) still sees the old, pre-rebuild site.

To go live: run `python3 prepare_deploy.py` (writes self-contained pages into `dist/`),
then go to the Cloudflare dashboard for the `sauna-for-all` Worker and upload every file
in `dist/` as a new deployment. `CMS_SETUP.md` describes a way to make this automatic
going forward (Cloudflare Workers Builds), but until that's set up, this manual step is
needed after every future content change too.

## 1. Content Becky needs to supply

- **Charter PDF.** The Charter page and several buttons link to
  `/files/public-sauna-bathing-charter.pdf`, but that file doesn't exist yet ("The Public
  Sauna-Bathing Charter, August 19, 2026" per SPEC.md's asset list). Downloads will 404
  until it's added.
- **FAQ content (V1, 16 Q&As).** SPEC.md calls for the exact text of 16 questions from
  `/content/faqs.md`, which was never supplied or found in the shared Drive folder. The
  FAQs page currently shows the 7 real questions that were live on the previous site, as
  a genuine interim (not fabricated) set, with a note on the page that more are coming.
  Swap-in instructions are in a code comment at the top of `page_faqs()` in `build.py`.
- **Style guide PDF.** Never supplied (`SFA_StyleGuide.pdf` in SPEC.md's asset list).
  Colours, type, and icon treatment were built from the rest of the spec and the
  previous site, but haven't been checked against an actual style guide document.
- **Updated logo file.** SPEC.md names a "Logo (updated)" Drive folder, but it was empty
  when checked. The site currently uses an inline text wordmark (the same treatment as
  the previous site) rather than a real logo file, in the header and footer of every
  page.
- **Substack address.** Referenced as `[ADD LINK]` in SPEC.md Section 4 and needed for
  the News feed. Without it: every "Sign up" and "Newsletter" link on every page (there
  are about a dozen) currently points nowhere (`#`), and the News page shows its empty
  state ("News is on its way") instead of real posts. The feed-fetching Cloudflare Worker
  is already built and tested (`workers/substack-feed/`) -- once the address is known,
  deploying it is a few `wrangler` commands (see that folder's `README.md`).
- **Press logos + "all coverage" link.** SPEC.md's "As featured in" section needs at
  least 3 logos from a Drive folder that doesn't exist yet; it stays correctly hidden
  until then. The Section 4 "See all coverage" link is also still `[ADD LINK]`.
- **Resources content.** The Resources page's four categories (Guidance, Case studies,
  Research library, Templates and tools) all show "Coming soon" because the spreadsheet
  "Resources" tab SPEC.md references doesn't exist yet.
- **Regional partners.** The Signatories page has a dedicated section for these; there's
  no source list yet, so it correctly shows the spec's own "coming soon" copy.
- **Contact form's real backend.** SPEC.md leaves open exactly how messages should reach
  `hei@saunaforall.org` (a Cloudflare Worker plus an email service is one option). As a
  working interim, the form currently builds a `mailto:` link and hands off to the
  visitor's own email app on submit -- it genuinely sends, just via the visitor's mail
  client rather than a server, which is worth testing once and replacing once the real
  approach is decided.

## 2. Small data things worth a second look

- One real, consented signatory's organisation name is entered as "SaunaGlo (and
  Willamette Sauna Festivaali ?)" -- the literal question mark suggests uncertain data
  entry at the source (the Google Form response). Left exactly as submitted rather than
  edited, but worth Becky confirming with that signatory.
- The Drive photo caption for `sauna-for-all-2026-05.jpg` spells a founding steward's
  name "Ian Wheelan"; the Founding Stewards list in `build.py` (and the Google Form data)
  spells it "Ian Whelan." Worth confirming the correct spelling.
- No individual headshots exist for any of the 10 founding stewards or 3 advisors -- the
  About page shows initials in a circle for all of them. Two stewards (Steve Crosbie and
  Ian Whelan/Wheelan) do appear together in a real photo
  (`images/photos/sauna-for-all-2026-05.jpg`), but using a two-person photo as one
  person's individual avatar would misrepresent it, so it wasn't used that way.
- Two of the four real Drive photos (`sauna-for-all-2026-04.jpg` and `-05.jpg`) aren't
  currently used anywhere on the site -- available if a spot comes up for them.

## 3. Infrastructure that needs account access this project doesn't have

- **Domain cutover** (saunaforall.org -> the Cloudflare Worker): steps in
  `DOMAIN_CUTOVER.md`.
- **CMS setup** (Sveltia CMS + Cloudflare Workers Builds, so Becky can edit FAQs,
  Resources, press logos, and regional partners without touching code): plan and open
  decisions in `CMS_SETUP.md`. Not started -- needs a Cloudflare account and a decision
  on which content should be self-editable.

## 4. Already handled, no action needed

Signatories (live Google Sheet, consent-gated, grouped by organisation), the design
system, navigation/footer, all eight pages' layout and copy, the Substack feed proxy
Worker (built and tested, just not deployed), and the Section 9 QA pass (which caught
and fixed three real bugs this round: hidden em-dash HTML entities on three pages, the
Home page hero showing literal placeholder text instead of a photo, and a JavaScript
crash in the signatory logo fallback).
