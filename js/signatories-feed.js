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

  function logoTile(s) {
    var domain = s.logoDomain || '';
    var initials = (s.name || '').split(/\s+/).filter(Boolean).map(function (w) { return w[0]; }).join('').slice(0, 3).toUpperCase();
    if (!domain) {
      return '<div class="logo-tile" style="width:80px; height:80px; border-radius:50%; border:none; background:var(--light-blue); font-size:0.85rem; font-weight:800; color:var(--green-dark);">' + escapeHtml(initials) + '</div>';
    }
    // Same public, keyless favicon lookup build.py uses for the build-time
    // cards, so a signatory added only through the live feed looks
    // identical to one baked in at build time.
    var logoUrl = 'https://www.google.com/s2/favicons?domain=' + encodeURIComponent(domain) + '&sz=128';
    return '<div class="logo-tile" style="width:80px; height:80px; padding:4px; overflow:hidden;">' +
      '<img src="' + escapeHtml(logoUrl) + '" alt="' + escapeHtml(s.name + ' logo') + '" loading="lazy" ' +
      'style="max-width:100%; max-height:100%; object-fit:contain;" ' +
      'onerror="var p=this.parentElement; p.textContent=\'' + escapeHtml(initials) + '\'; p.style.padding=\'8px\';">' +
      '</div>';
  }

  function categoryPills(cats) {
    return (cats || []).map(function (c) { return '<span class="category-pill">' + escapeHtml(c) + '</span>'; }).join('');
  }

  function renderCard(s) {
    var catsAttr = (s.categories || []).join('|');
    var searchAttr = [s.name, s.signedBy || '', s.country || ''].join(' ');
    var hasUrl = s.url && s.url !== '#';
    var nameHtml = hasUrl
      ? '<a href="' + escapeHtml(s.url) + '" class="signatory-name-link" target="_blank" rel="noopener">' + escapeHtml(s.name) + '</a>'
      : '<span class="signatory-name-link">' + escapeHtml(s.name) + '</span>';
    var signedByHtml = s.signedBy ? '<div class="small muted">' + escapeHtml(s.signedBy) + '</div>' : '';
    var commitmentHtml = s.commitment ? '<p class="signatory-commitment">&ldquo;' + escapeHtml(s.commitment) + '&rdquo;</p>' : '';
    return '<div class="signatory-card" data-categories="' + escapeHtml(catsAttr) + '" data-search="' + escapeHtml(searchAttr) + '" data-country="' + escapeHtml(s.country || '') + '">' +
      '<div class="signatory-card-top">' + logoTile(s) + '<div class="category-pills">' + categoryPills(s.categories) + '</div></div>' +
      nameHtml + signedByHtml +
      '<div class="signatory-country">' + escapeHtml(s.country || '') + '</div>' +
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
        if (cEl && typeof data.countries === 'number') cEl.textContent = String(data.countries);
      }

      if (grid && Array.isArray(data.signatories)) {
        grid.innerHTML = data.signatories.map(renderCard).join('');
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
