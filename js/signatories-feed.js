// Signatories directory + homepage tally: live data (SPEC.md Section 7.1).
// Reads from the Cloudflare Worker feed proxy (workers/signatories-feed/)
// once it's deployed and SIGNATORIES_FEED_ENDPOINT is set in build.py. Until
// then (or if the fetch fails), both the signatories grid and the homepage
// "Signatories / Countries" counters keep showing whatever was baked in at
// the last build -- there is nothing to fake here: this file either
// refreshes the page with live data or gets out of the way, same approach
// as js/news-feed.js takes for the News page.
document.addEventListener('DOMContentLoaded', function () {
  var counterSection = document.getElementById('counter');
  var grid = document.getElementById('signatoriesGrid');
  var endpoint = (grid && grid.dataset.feedEndpoint) || (counterSection && counterSection.dataset.feedEndpoint);
  if (!endpoint) return; // no live source configured -- build-time snapshot stands as-is

  function escapeHtml(s) {
    var div = document.createElement('div');
    div.textContent = s == null ? '' : String(s);
    return div.innerHTML;
  }

  // Badge letters, matching build.py's _initials: punctuation stripped,
  // lowercase connectives ignored, single words shortened to three characters.
  function badgeInitials(name) {
    var words = name.split(/\s+/)
      .map(function (w) { return w.replace(/[^0-9A-Za-z\u00C0-\u024F]/g, ''); })
      .filter(Boolean);
    var significant = words.filter(function (w) { return w !== w.toLowerCase(); });
    if (!significant.length) significant = words;
    if (!significant.length) return '?';
    if (significant.length === 1) return significant[0].slice(0, 3).toUpperCase();
    return significant.map(function (w) { return w[0]; }).join('').slice(0, 3).toUpperCase();
  }

  function slugify(name) {
    return (name || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
  }

  function logoTile(s) {
    var initials = badgeInitials(s.name || '');
    // Round 2: no third-party favicon lookup. Every signatory gets an
    // initials badge unless we host a logo for them ourselves. build.py
    // writes the map of self-hosted logos into the page as
    // window.SIGNATORY_LOGOS, so a card rendered from the live feed matches
    // one baked in at build time.
    var logos = window.SIGNATORY_LOGOS || {};
    var logoPath = logos[slugify(s.name)];
    if (logoPath) {
      return '<div class="logo-tile" style="width:80px; height:80px; padding:4px; overflow:hidden;">' +
        '<img src="' + escapeHtml(logoPath) + '" alt="' + escapeHtml(s.name + ' logo') + '" loading="lazy" ' +
        'style="max-width:100%; max-height:100%; object-fit:contain;">' +
        '</div>';
    }
    return '<div class="logo-tile" style="width:80px; height:80px; border-radius:50%; border:none; background:var(--light-blue); font-size:0.85rem; font-weight:800; color:var(--green-dark);">' + escapeHtml(initials) + '</div>';
  }

  // Mirrors _COUNTRY_ALIASES / _normalize_country in build.py.
  var COUNTRY_ALIASES = {
    uk: 'United Kingdom', gb: 'United Kingdom', gbr: 'United Kingdom',
    greatbritain: 'United Kingdom', unitedkingdom: 'United Kingdom',
    unitedkingdomofgreatbritainandnorthernireland: 'United Kingdom',
    us: 'United States', usa: 'United States', unitedstates: 'United States',
    unitedstatesofamerica: 'United States', america: 'United States'
  };
  function normalizeCountry(country) {
    var c = String(country == null ? '' : country).trim().replace(/^[.,]+|[.,]+$/g, '');
    if (!c) return '';
    var key = c.toLowerCase().replace(/[^a-z]/g, '');
    return COUNTRY_ALIASES[key] || c;
  }
  // The card label, canonicalising only the country part (mirrors
  // _tidy_country in build.py), so "UK" and "United Kingdom" don't show as
  // different places on neighbouring cards.
  function tidyCountry(raw) {
    var parts = String(raw == null ? '' : raw).split(',')
      .map(function (p) { return p.trim(); }).filter(Boolean);
    if (!parts.length) return '';
    parts[parts.length - 1] = normalizeCountry(parts[parts.length - 1]);
    return parts.join(', ');
  }

  // Distinct countries across the signatories, counted after folding the
  // spellings together. null when there is nothing to count from.
  function countCountries(list) {
    if (!Array.isArray(list) || !list.length) return null;
    var seen = {}, n = 0;
    list.forEach(function (s) {
      var parts = String(s.country == null ? '' : s.country).split(',');
      var c = normalizeCountry(parts[parts.length - 1]);
      if (c && !seen[c]) { seen[c] = true; n++; }
    });
    return n;
  }

  // Mirrors _order_key() in build.py -- change both together.
  function orderKey(name) {
    return (name || '').toLowerCase().replace(/[^0-9a-zÀ-ɏ]+/g, '');
  }

  // The feed returns signatories with no sign-up date attached, so it can't
  // order them itself -- and since this file replaces the whole grid, its
  // order would otherwise win. build.py works the order out from the
  // sheet's Timestamp column and leaves it in window.SIGNATORY_ORDER, so
  // the live refresh reproduces it instead of overriding it. Anyone the
  // feed knows about who wasn't in the last build has signed since, so they
  // belong after everyone else -- which is exactly where an unknown name
  // lands here.
  function orderBySignupDate(list) {
    var order = window.SIGNATORY_ORDER;
    if (!Array.isArray(order) || !order.length) return list;
    var rank = {};
    order.forEach(function (key, i) { if (!(key in rank)) rank[key] = i; });
    return list
      .map(function (s, i) {
        // Split cards carry their own key (they share their organisation's
        // name, so the name can't identify them); everything else keys by name.
        var r = rank[s._key || orderKey(s.name)];
        return { s: s, rank: r === undefined ? order.length : r, i: i };
      })
      .sort(function (a, b) { return a.rank - b.rank || a.i - b.i; })
      .map(function (e) { return e.s; });
  }

  // Re-applies the splits build.py made. The feed groups everyone from one
  // organisation onto a single card with a single quote; where the build gave
  // a second person their own card to carry their own commitment, this puts
  // that card back and takes their name off the main card's "Signed by" line.
  // Anyone who joins an organisation between deploys stays grouped until the
  // next build, which is when their split is worked out.
  function applySplits(list) {
    var splits = window.SIGNATORY_SPLITS;
    if (!splits || typeof splits !== 'object') return list;
    var out = list.slice();
    Object.keys(splits).forEach(function (orgKey) {
      var entry = splits[orgKey];
      var main = null;
      for (var i = 0; i < out.length; i++) {
        if (!out[i]._key && orderKey(out[i].name) === orgKey) { main = out[i]; break; }
      }
      if (!main) return; // organisation no longer in the feed -- nothing to split
      if (entry.signedBy) main.signedBy = entry.signedBy;
      (entry.cards || []).forEach(function (c) {
        out.push({
          _key: c.key, name: c.name, signedBy: c.signedBy, url: c.url,
          country: c.country, categories: c.categories, commitment: c.commitment
        });
      });
    });
    return out;
  }

  function categoryPills(cats) {
    return (cats || []).map(function (c) { return '<span class="category-pill">' + escapeHtml(c) + '</span>'; }).join('');
  }

  function renderCard(s) {
    var catsAttr = (s.categories || []).join('|');
    var searchAttr = [s.name, s.signedBy || '', s.country || ''].join(' ');
    var hasUrl = s.url && s.url !== '#';
    // Wrapped in an <h3>, matching build.py's signatory_card -- the names
    // are the page's long tail of brand searches.
    var nameInner = hasUrl
      ? '<a href="' + escapeHtml(s.url) + '" class="signatory-name-link" target="_blank" rel="noopener">' + escapeHtml(s.name) + '</a>'
      : '<span class="signatory-name-link">' + escapeHtml(s.name) + '</span>';
    var nameHtml = '<h3 class="signatory-name">' + nameInner + '</h3>';
    var signedByHtml = s.signedBy ? '<div class="small muted">' + escapeHtml(s.signedBy) + '</div>' : '';
    var commitmentHtml = s.commitment ? '<p class="signatory-commitment">&ldquo;' + escapeHtml(s.commitment) + '&rdquo;</p>' : '';
    return '<div class="signatory-card" data-categories="' + escapeHtml(catsAttr) + '" data-search="' + escapeHtml(searchAttr) + '" data-country="' + escapeHtml(s.country || '') + '">' +
      '<div class="signatory-card-top"><div class="category-pills">' + categoryPills(s.categories) + '</div>' + logoTile(s) + '</div>' +
      nameHtml + signedByHtml +
      '<div class="signatory-country">' + escapeHtml(tidyCountry(s.country)) + '</div>' +
      commitmentHtml +
      '</div>';
  }

  fetch(endpoint)
    .then(function (r) { return r.json(); })
    .then(function (data) {
      if (!data) return;

      if (counterSection && typeof data.count === 'number') {
        var sEl = document.getElementById('statSignatories');
        var cEl = document.getElementById('statCountries');
        if (sEl) sEl.textContent = String(data.count);
        if (cEl) {
          // The feed counts "UK" and "United Kingdom" as two countries, so
          // its own total is recounted here from the signatories it sent,
          // with the spellings folded together (see _normalize_country in
          // build.py -- the two alias tables have to stay in step). Falls
          // back to the feed's number if it sent no signatories.
          var n = countCountries(data.signatories);
          if (n === null && typeof data.countries === 'number') n = data.countries;
          if (n !== null) cEl.textContent = String(n);
        }
      }

      if (grid && Array.isArray(data.signatories)) {
        grid.innerHTML = orderBySignupDate(applySplits(data.signatories)).map(renderCard).join('');
        // Re-run the filter/search wiring from main.js now that the grid
        // has an entirely new set of .signatory-card elements -- it reads
        // the DOM fresh each call, so this is safe to call repeatedly.
        if (typeof window.initSignatoryFilters === 'function') window.initSignatoryFilters();
      }
    })
    .catch(function () {
      // Feed unreachable -- leave the build-time snapshot showing rather
      // than surface a broken/blank section.
    });
});
