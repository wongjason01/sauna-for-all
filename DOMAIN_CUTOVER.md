# Pointing saunaforall.org at the new site

The site is deployed as a Cloudflare Worker (static assets), currently reachable at the
default `*.workers.dev` address rather than the real domain. saunaforall.org is already
registered (per earlier notes in this project); this is how to connect it once the rebuilt
site is deployed and approved for launch.

## 1. Check where the domain's DNS is managed

Look up saunaforall.org's nameservers (e.g. `dig NS saunaforall.org` from a terminal, or a
site like whatsmydns.net). There are two cases:

**Case A: Nameservers already point to Cloudflare** (they'll look like
`xxx.ns.cloudflare.com`). The domain is already active in a Cloudflare account. Skip to
step 2.

**Case B: Nameservers point somewhere else** (the registrar's own DNS, GoDaddy, Namecheap,
etc.). Two options:
- Move the domain's nameservers to Cloudflare: add the domain as a new "site" in the
  Cloudflare dashboard, which gives two Cloudflare nameservers to set at the registrar.
  This is the standard path and also gives free SSL, caching, and analytics.
- Or, if the domain must stay on its current DNS provider, a Worker custom domain still
  needs the domain's DNS to be on Cloudflare -- Cloudflare Workers custom domains do not
  support "external DNS with a CNAME," so moving nameservers is effectively required for
  this hosting setup.

Changing nameservers can take anywhere from a few minutes to 24-48 hours to propagate
fully, so this step should happen first and with some lead time before the target launch
date, not on launch day itself.

## 2. Attach the domain to the Worker

Once saunaforall.org is active in the Cloudflare account (Case A, or after completing
Case B):

1. Go to the Cloudflare dashboard -> Workers & Pages -> the `sauna-for-all` Worker.
2. Open the **Settings** tab -> **Domains & Routes**.
3. Click **Add** -> **Custom Domain**.
4. Enter `saunaforall.org` (and, in a separate step, `www.saunaforall.org` if the site
   should also answer on the www subdomain).
5. Cloudflare provisions an SSL certificate automatically -- this usually takes a few
   minutes, occasionally longer.

## 3. Decide on the www vs bare-domain redirect

Pick one as the canonical address and redirect the other to it (search engines and
sharing links prefer a single canonical URL):

- Add both `saunaforall.org` and `www.saunaforall.org` as custom domains on the Worker.
- Add a Cloudflare Redirect Rule (Rules -> Redirect Rules in the dashboard) sending one to
  the other with a 301, e.g. `www.saunaforall.org/*` -> `https://saunaforall.org/$1`.

## 4. Verify before announcing the new address

- Load `https://saunaforall.org` directly and click through every nav link.
- Confirm the padlock/certificate is valid (Cloudflare's automatic SSL).
- Check `https://www.saunaforall.org` redirects correctly if that's set up.
- Re-run the Section 9 "Done" checklist against the live domain, not just the
  `workers.dev` address -- a few things (favicon, absolute links, share previews) can
  behave differently once real domain matters (e.g. Open Graph tags reading the request's
  own host).

## 5. After cutover

- If the CMS (Sveltia + Cloudflare Workers Builds git auto-deploy -- see
  `CMS_SETUP.md`) is wired up, double check its auth Worker and any redirect URLs
  reference `saunaforall.org` rather than the `workers.dev` address, since OAuth-style
  callbacks are often locked to a specific host.
- Update anywhere the old `workers.dev` URL might have been shared already (social bios,
  the Google Form's own confirmation text if it links back to the site, etc.) to the real
  domain.

## What I can't do from here

Attaching a custom domain and changing nameservers both require access to the Cloudflare
account and (for Case B) the domain registrar's account -- credentials this project
doesn't have and shouldn't be given to an automated process. This document is the
step-by-step for whoever has that access (Jason or Becky) to follow in the Cloudflare and
registrar dashboards directly.
