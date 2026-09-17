/**
 * Sauna for All -- Substack feed proxy (SPEC.md Section 7.2)
 *
 * Browsers cannot fetch Substack's RSS feed directly (Substack blocks
 * cross-origin requests from the page), so this small Cloudflare Worker
 * fetches it server-side, converts it to JSON, and caches the result for
 * an hour so the News page still loads fast (and still loads at all) if
 * Substack is slow or briefly down.
 *
 * NOT YET DEPLOYED. This is blocked on SPEC.md Section 8, open question 1:
 * the Sauna for All Substack address hasn't been provided yet. Once it
 * has:
 *   1. Set SUBSTACK_FEED_URL below (the publication's address + "/feed").
 *   2. `wrangler deploy` this worker (see wrangler.toml in this folder).
 *   3. Set NEWS_FEED_ENDPOINT in build.py to this worker's URL and
 *      rebuild the site -- the News page's JS (js/news-feed.js) will then
 *      start rendering real posts instead of the "News is on its way"
 *      empty state.
 *
 * Returns JSON: { posts: [ { title, link, date, summary, image } ], fetchedAt }
 * `posts` is newest-first, capped at 20 items per SPEC.md 7.2.
 */

const SUBSTACK_FEED_URL = ""; // e.g. "https://saunaforall.substack.com/feed"
const CACHE_TTL_SECONDS = 60 * 60; // refresh at most once an hour, per spec
const MAX_POSTS = 20;

const CACHE_URL = "https://sauna-for-all-substack-feed.internal/substack-feed-cache";

export default {
  async fetch(request, env, ctx) {
    const origin = request.headers.get("Origin") || "*";
    const corsHeaders = {
      "Access-Control-Allow-Origin": origin,
      "Access-Control-Allow-Methods": "GET, OPTIONS",
      "Vary": "Origin",
    };

    if (request.method === "OPTIONS") {
      return new Response(null, { headers: corsHeaders });
    }

    const feedUrl = env.SUBSTACK_FEED_URL || SUBSTACK_FEED_URL;
    if (!feedUrl) {
      return json({ posts: [], fetchedAt: new Date().toISOString(), error: "SUBSTACK_FEED_URL not configured" }, corsHeaders, 200);
    }

    const cache = caches.default;
    const cached = await cache.match(CACHE_URL);
    if (cached) return withCors(cached, corsHeaders);

    try {
      const { posts, fetchedAt } = await fetchAndCache(feedUrl, cache, ctx);
      return json({ posts, fetchedAt }, corsHeaders, 200);
    } catch (err) {
      return json({ posts: [], fetchedAt: new Date().toISOString(), error: String(err) }, corsHeaders, 200);
    }
  },

  // Cron trigger (see wrangler.toml): warms the cache every hour even with
  // no visitors, per SPEC.md 7.2 ("The Worker refreshes the feed every
  // hour and stores a copy").
  async scheduled(event, env, ctx) {
    const feedUrl = env.SUBSTACK_FEED_URL || SUBSTACK_FEED_URL;
    if (!feedUrl) return;
    ctx.waitUntil(fetchAndCache(feedUrl, caches.default, ctx).catch(() => {}));
  },
};

async function fetchAndCache(feedUrl, cache, ctx) {
  const resp = await fetch(feedUrl, { headers: { "User-Agent": "SaunaForAllSite/1.0 (+https://saunaforall.org)" } });
  if (!resp.ok) throw new Error(`feed fetch failed: ${resp.status}`);
  const xml = await resp.text();
  const posts = parseRss(xml).slice(0, MAX_POSTS);
  const fetchedAt = new Date().toISOString();
  const cacheableResponse = new Response(JSON.stringify({ posts, fetchedAt }), {
    status: 200,
    headers: { "Content-Type": "application/json", "Cache-Control": `public, max-age=${CACHE_TTL_SECONDS}` },
  });
  ctx.waitUntil(cache.put(CACHE_URL, cacheableResponse));
  return { posts, fetchedAt };
}

function json(data, corsHeaders, status) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json", ...corsHeaders },
  });
}

function withCors(response, corsHeaders) {
  const headers = new Headers(response.headers);
  for (const [k, v] of Object.entries(corsHeaders)) headers.set(k, v);
  return new Response(response.body, { status: response.status, headers });
}

/**
 * Minimal, dependency-free RSS 2.0 parser -- Workers has no DOMParser, and
 * pulling in a full XML library for a handful of fields per item isn't
 * worth the bundle size. Substack's feed format is stable and simple
 * enough that a regex-based item splitter is reliable here.
 */
function parseRss(xml) {
  const items = xml.split("<item>").slice(1).map((chunk) => chunk.split("</item>")[0]);
  return items.map((item) => {
    const title = decodeEntities(tag(item, "title"));
    const link = decodeEntities(tag(item, "link"));
    const pubDate = tag(item, "pubDate");
    const description = decodeEntities(stripHtml(tag(item, "description")));
    const image = attr(item, "enclosure", "url") || firstImgSrc(tag(item, "description") || "");
    return {
      title,
      link,
      date: pubDate ? new Date(pubDate).toISOString() : null,
      summary: firstSentence(description),
      image: image || null,
    };
  }).filter((p) => p.title && p.link);
}

function tag(xml, name) {
  const m = xml.match(new RegExp(`<${name}[^>]*>([\\s\\S]*?)</${name}>`, "i"));
  if (!m) return "";
  return m[1].replace(/^<!\[CDATA\[/, "").replace(/\]\]>$/, "").trim();
}

function attr(xml, tagName, attrName) {
  const m = xml.match(new RegExp(`<${tagName}[^>]*\\s${attrName}="([^"]*)"`, "i"));
  return m ? m[1] : "";
}

function firstImgSrc(html) {
  const m = html.match(/<img[^>]+src="([^"]+)"/i);
  return m ? m[1] : "";
}

function stripHtml(html) {
  return html.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
}

function firstSentence(text) {
  const m = text.match(/^.*?[.!?](\s|$)/);
  const sentence = (m ? m[0] : text).trim();
  return sentence.length > 180 ? sentence.slice(0, 177).trim() + "…" : sentence;
}

function decodeEntities(str) {
  return (str || "")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'");
}
