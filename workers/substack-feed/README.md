# Substack feed proxy (not yet deployed)

Implements SPEC.md Section 7.2: the News page reads posts from the Sauna
for All Substack, but browsers can't fetch a Substack RSS feed directly,
so this Cloudflare Worker fetches it server-side, converts it to JSON, and
caches the result for an hour.

## Why this isn't live yet

SPEC.md Section 8, open question 1, still needs an answer from Becky: the
Substack publication address hasn't been provided. Nothing below can be
completed until that link exists.

## Deploying, once the Substack link is known

1. `cd workers/substack-feed`
2. `npx wrangler login` (once per machine)
3. `npx wrangler secret put SUBSTACK_FEED_URL` and paste the feed address
   (the Substack's normal URL with `/feed` appended, e.g.
   `https://saunaforall.substack.com/feed`)
4. `npx wrangler deploy`
5. Wrangler prints the deployed Worker's URL
   (`https://sauna-for-all-substack-feed.<your-subdomain>.workers.dev`).
   Set that as `NEWS_FEED_ENDPOINT` near the top of `build.py` in the
   project root, then rebuild and redeploy the main site. The News page's
   `js/news-feed.js` will start rendering real posts instead of the
   "News is on its way" empty state -- no other code changes needed.

This is a separate Cloudflare Worker project from the main site's Worker
(the one serving the static HTML/CSS/JS) -- it does not need to live on
the same domain, and CORS is already handled in `worker.js` so the main
site can call it cross-origin.
