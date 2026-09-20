# Pointing saunaforall.org at the new site

The site is deployed as a Cloudflare Worker (static assets), currently reachable at the
default `*.workers.dev` address. This is how to move saunaforall.org onto it.

Written against the real zone file exported from GoDaddy on 2026-09-20. If the zone has
changed since, re-export and re-check before following this.

## The one thing that can go badly wrong

**This domain carries live email.** `MX` points at
`saunaforall-org.mail.protection.outlook.com` — Microsoft 365, provisioned through
GoDaddy (hence the `NETORGFT21144491.onmicrosoft.com` verification record and the
GoDaddy-flavoured SPF). Moving nameservers to Cloudflare without carrying every mail
record across stops mail reaching hei@saunaforall.org, and it fails quietly: senders get
bounces, the mailbox just looks unusually quiet.

Two details make it less forgiving than a typical move:

- `_dmarc` is set to `p=quarantine`. If SPF or DKIM don't line up after the move,
  legitimate mail goes to recipients' spam folders rather than failing loudly.
- The DKIM records are CNAMEs, so if either is wrong or missing, signing breaks.

The safety net is that **Cloudflare holds a new zone inactive until the nameservers
actually change.** So every record can be created and checked in the Cloudflare
dashboard first, and the GoDaddy switch becomes the last step rather than the first.
Do it in that order.

## 1. Add the domain to Cloudflare (nothing goes live yet)

Use the **same Cloudflare account that holds the `sauna-for-all` Worker** — a custom
domain can only attach to a Worker in the same account.

Dashboard → Add a site → `saunaforall.org` → Free plan → let the scan run. It will
import most of what's below automatically. Treat the import as a draft, not as done:
with a GoDaddy-managed Microsoft 365 tenant the scan does sometimes miss the DKIM and
autodiscover entries.

## 2. Check every record against this table

This is the full set to exist in Cloudflare before the nameservers move. Add anything
missing; correct anything that differs.

| Type | Name | Value | Proxy |
|---|---|---|---|
| MX | `@` | `saunaforall-org.mail.protection.outlook.com` (priority 0) | — |
| TXT | `@` | `NETORGFT21144491.onmicrosoft.com` | — |
| TXT | `@` | `v=spf1 include:secureserver.net -all` | — |
| TXT | `_dmarc` | `v=DMARC1; p=quarantine; adkim=r; aspf=r; rua=mailto:dmarc_rua@onsecureserver.net;` | — |
| CNAME | `autodiscover` | `autodiscover.outlook.com` | DNS only |
| CNAME | `selector1._domainkey` | `selector1-saunaforall-org._domainkey.netorgft21144491.p-v1.dkim.mail.microsoft` | DNS only |
| CNAME | `selector2._domainkey` | `selector2-saunaforall-org._domainkey.netorgft21144491.p-v1.dkim.mail.microsoft` | DNS only |
| CNAME | `msoid` | `clientconfig.microsoftonline-p.net` | DNS only |
| CNAME | `lyncdiscover` | `webdir.online.lync.com` | DNS only |
| CNAME | `sip` | `sipdir.online.lync.com` | DNS only |
| CNAME | `email` | `email.secureserver.net` | DNS only |
| SRV | `_sip._tls` | priority 100, weight 1, port 443, target `sipdir.online.lync.com` | — |
| SRV | `_sipfederationtls._tcp` | priority 100, weight 1, port 5061, target `sipfed.online.lync.com` | — |

**Every CNAME above must be "DNS only" (grey cloud), not proxied.** Cloudflare defaults
some CNAMEs to proxied, and a proxied `autodiscover` breaks Outlook's account setup.
Only the website records get the orange cloud.

Deliberately **not** carried over:

- `A @ → WebsiteBuilder Site` — the GoDaddy Website Builder page currently at the apex.
  The Worker replaces it. Confirm nobody still depends on that page before cutting over.
- `CNAME www → @` — `www` becomes its own custom domain on the Worker (step 4) rather
  than a CNAME.
- `_domainconnect` — GoDaddy's own automation hook; meaningless once DNS is elsewhere.
- `NS` and `SOA` — Cloudflare supplies its own.

Copy SPF and DMARC **exactly as they are**. The SPF authorises `secureserver.net` rather
than `spf.protection.outlook.com`, which looks wrong for Microsoft 365 but is what
GoDaddy's resold tenants use. A DNS move is not the moment to also change mail policy —
change one thing at a time, and revisit SPF separately afterwards if it needs it.

Verify the two DKIM targets against Microsoft 365 admin centre (Settings → Domains →
saunaforall.org → DNS records) rather than trusting the export. If GoDaddy's exporter
truncated them, mail still flows but arrives unsigned, and `p=quarantine` then pushes it
to spam.

## 3. Change the nameservers at GoDaddy

Only once step 2 is complete. GoDaddy → My Products → saunaforall.org → DNS →
Nameservers → Change → "I'll use my own nameservers" → enter the two Cloudflare
nameservers shown on the Cloudflare overview page.

Propagation is usually well under an hour for GoDaddy, but allow up to 48. Don't do this
on the morning of a launch or the day before anyone's away.

Keep the exported zone file. It is the rollback: setting the nameservers back to
`ns57`/`ns58.domaincontrol.com` restores the old setup exactly.

## 4. Attach the domain to the Worker

Cloudflare dashboard → Workers & Pages → `sauna-for-all` → Settings → Domains & Routes →
Add → Custom Domain. Add `saunaforall.org`, then repeat for `www.saunaforall.org`.
Certificates are issued automatically, usually within a few minutes.

## 5. Pick one canonical address

Search engines and share previews want a single address. Add both as custom domains,
then Rules → Redirect Rules → 301 from the one you don't want to the one you do, e.g.
`www.saunaforall.org/*` → `https://saunaforall.org/$1`.

## 6. Turn off the workers.dev address

Settings → Domains & Routes → disable the `workers.dev` route. This leaves exactly one
copy of the site on the internet, so the preview address can't be indexed alongside the
real one or linger in anyone's bookmarks. Do this only after the custom domain is
confirmed working.

## 7. Verify — mail first, then the site

Mail is the part that fails silently, so check it first:

- Send a message from an outside address to hei@saunaforall.org and confirm it arrives.
- Send one *from* the domain to an outside address and check the headers show SPF and
  DKIM passing.
- Confirm Outlook can still set up the account from scratch (that's `autodiscover`).

Then the site: load `https://saunaforall.org`, click every nav link, confirm the
certificate is valid, confirm `www` redirects, and re-check the share preview and
favicon behaviour now that a real domain is in play.

## 8. Afterwards

- Update `SITE_URL` in `build.py` (see the SEO notes) so canonical tags, Open Graph URLs
  and the sitemap all point at the real domain, and redeploy.
- Update anywhere the workers.dev address was shared — social bios, the Google Form's
  confirmation text, the Substack.
- Note for later: with DNS off GoDaddy, GoDaddy can no longer auto-manage the Microsoft
  365 records. If Microsoft rotates DKIM keys or adds a record, it has to be applied in
  Cloudflare by hand.

## What can't be done from here

Changing nameservers and attaching custom domains need the GoDaddy and Cloudflare
account logins, which this project doesn't hold and shouldn't. This document is the
click-by-click for whoever does.
