document.addEventListener('DOMContentLoaded', function () {
  var toggle = document.getElementById('navToggle');
  var links = document.getElementById('navLinks');
  if (toggle && links) {
    toggle.addEventListener('click', function () {
      var open = links.classList.toggle('open');
      toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
    links.querySelectorAll('a').forEach(function (a) {
      a.addEventListener('click', function () {
        links.classList.remove('open');
        toggle.setAttribute('aria-expanded', 'false');
      });
    });
  }

  // Contact form (SPEC.md Section 6.8). There is no backend mail service
  // wired up yet (see SPEC.md Section 8, open question 2 -- how messages
  // should reach hei@saunaforall.org is still unanswered), so this opens a
  // pre-filled mailto: to that inbox as an interim delivery mechanism that
  // actually works with no server, rather than showing a fake success
  // message that silently drops the message. Replace with a real fetch()
  // to a Cloudflare Worker + email service once that's decided.
  var contactForm = document.getElementById('contactForm');
  if (contactForm) {
    var reasonSelect = document.getElementById('contactReason');
    var params = new URLSearchParams(window.location.search);
    if (reasonSelect && params.get('reason') === 'media') {
      reasonSelect.value = 'Media enquiry';
    }
    contactForm.addEventListener('submit', function (e) {
      e.preventDefault();
      var name = document.getElementById('contactName').value.trim();
      var email = document.getElementById('contactEmail').value.trim();
      var reason = reasonSelect.value;
      var message = document.getElementById('contactMessage').value.trim();
      var subject = 'Sauna for All contact form: ' + (reason || 'General question');
      var body = 'Name: ' + name + '\nEmail: ' + email + '\nReason: ' + reason + '\n\n' + message;
      var mailto = 'mailto:hei@saunaforall.org?subject=' + encodeURIComponent(subject) + '&body=' + encodeURIComponent(body);
      window.location.href = mailto;
      var success = document.getElementById('contactSuccess');
      if (success) success.style.display = 'block';
    });
  }

  // Signatories directory: category filter (multi-select toggle chips) + text
  // search. Exposed as window.initSignatoryFilters so js/signatories-feed.js
  // can re-run it after replacing #signatoriesGrid's contents with live data
  // from the feed Worker -- the chip/search listeners themselves only need
  // wiring up once, but the card list they filter has to be re-read fresh
  // each time it's called, since a re-run after a live-data refresh has an
  // entirely new set of .signatory-card elements to work with.
  // Paging state lives out here rather than inside initSignatoryFilters
  // because the "Show more" button is wired up exactly once, while
  // initSignatoryFilters runs again every time the live feed swaps the
  // cards out. If the button closed over a variable from the first run it
  // would keep paging a set of cards that no longer exists.
  var signatoryLimit = 0;
  var signatoryApply = null;

  function initSignatoryFilters() {
    var filterWrap = document.getElementById('signatoryFilters');
    var searchInput = document.getElementById('signatorySearch');
    var grid = document.getElementById('signatoriesGrid');
    if (!filterWrap || !grid) return;

    var allChip = filterWrap.querySelector('.filter-chip[data-category=""]');
    var catChips = Array.prototype.slice.call(filterWrap.querySelectorAll('.filter-chip[data-category]:not([data-category=""])'));
    var emptyMsg = document.getElementById('signatoryEmpty');
    var moreBtn = document.getElementById('signatoryShowMore');
    var pageSize = parseInt(grid.dataset.pageSize, 10) || 12;

    // A fresh set of cards, or a changed filter, starts again from the top.
    signatoryLimit = pageSize;

    function activeCategories() {
      return catChips.filter(function (c) { return c.classList.contains('active'); })
                      .map(function (c) { return c.dataset.category; });
    }

    function applyFilters() {
      var cats = activeCategories();
      var q = (searchInput && searchInput.value ? searchInput.value : '').trim().toLowerCase();
      var cards = Array.prototype.slice.call(grid.querySelectorAll('.signatory-card'));
      var matched = 0;
      var shown = 0;
      cards.forEach(function (card) {
        var cardCats = (card.dataset.categories || '').split('|');
        var matchesCat = cats.length === 0 || cats.some(function (c) { return cardCats.indexOf(c) !== -1; });
        var haystack = (card.dataset.search || '').toLowerCase();
        var matchesSearch = q === '' || haystack.indexOf(q) !== -1;
        var show = matchesCat && matchesSearch;
        if (show) matched++;
        // Cards past the current limit are still matches -- they're just
        // not on screen yet, so the count in the button stays honest.
        var onScreen = show && shown < signatoryLimit;
        if (onScreen) shown++;
        card.style.display = onScreen ? '' : 'none';
      });
      if (emptyMsg) emptyMsg.style.display = matched === 0 ? 'block' : 'none';
      if (moreBtn) {
        var remaining = matched - shown;
        moreBtn.hidden = remaining <= 0;
        moreBtn.textContent = 'Show ' + Math.min(remaining, pageSize) + ' more';
      }
    }
    signatoryApply = applyFilters;

    // Re-running this function (after a live-data refresh) would otherwise
    // stack duplicate click/input listeners onto the same chip and search
    // elements, since they're not recreated -- only the cards are. Guard
    // with a data flag so listeners are attached at most once, while
    // applyFilters() itself (which does need to see the new cards) always
    // runs.
    if (!filterWrap.dataset.filtersWired) {
      if (allChip) {
        allChip.addEventListener('click', function () {
          catChips.forEach(function (c) { c.classList.remove('active'); });
          allChip.classList.add('active');
          signatoryLimit = pageSize;
          applyFilters();
        });
      }
      catChips.forEach(function (chip) {
        chip.addEventListener('click', function () {
          if (allChip) allChip.classList.remove('active');
          chip.classList.toggle('active');
          if (activeCategories().length === 0 && allChip) allChip.classList.add('active');
          signatoryLimit = pageSize;
          applyFilters();
        });
      });
      if (searchInput) {
        searchInput.addEventListener('input', function () {
          signatoryLimit = pageSize;
          applyFilters();
        });
      }
      if (moreBtn) {
        moreBtn.addEventListener('click', function () {
          var before = grid.querySelectorAll('.signatory-card:not([style*="display: none"])').length;
          signatoryLimit += pageSize;
          if (signatoryApply) signatoryApply();
          // Send keyboard and screen-reader users to the first card that
          // just appeared, rather than leaving focus on a button that may
          // have vanished.
          var cards = Array.prototype.slice.call(grid.querySelectorAll('.signatory-card'))
            .filter(function (c) { return c.style.display !== 'none'; });
          var next = cards[before];
          var link = next && next.querySelector('.signatory-name-link');
          if (link) {
            if (!link.hasAttribute('tabindex') && link.tagName !== 'A') link.setAttribute('tabindex', '-1');
            link.focus();
          }
        });
      }
      filterWrap.dataset.filtersWired = '1';
    }

    applyFilters();
  }
  window.initSignatoryFilters = initSignatoryFilters;
  initSignatoryFilters();
});
