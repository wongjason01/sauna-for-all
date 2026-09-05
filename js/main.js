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

  // Simple mailto-based placeholder handlers for forms not yet wired to a backend
  document.querySelectorAll('form').forEach(function (form) {
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var btn = form.querySelector('button[type="submit"]');
      if (btn) {
        var original = btn.textContent;
        btn.textContent = 'Thank you!';
        setTimeout(function () { btn.textContent = original; }, 2200);
      }
    });
  });

  // Signatories directory: category filter (multi-select toggle chips) + text search
  var filterWrap = document.getElementById('signatoryFilters');
  var searchInput = document.getElementById('signatorySearch');
  var grid = document.getElementById('signatoriesGrid');
  if (filterWrap && grid) {
    var allChip = filterWrap.querySelector('.filter-chip[data-category=""]');
    var catChips = Array.prototype.slice.call(filterWrap.querySelectorAll('.filter-chip[data-category]:not([data-category=""])'));
    var cards = Array.prototype.slice.call(grid.querySelectorAll('.signatory-card'));
    var emptyMsg = document.getElementById('signatoryEmpty');

    function activeCategories() {
      return catChips.filter(function (c) { return c.classList.contains('active'); })
                      .map(function (c) { return c.dataset.category; });
    }

    function applyFilters() {
      var cats = activeCategories();
      var q = (searchInput && searchInput.value ? searchInput.value : '').trim().toLowerCase();
      var visible = 0;
      cards.forEach(function (card) {
        var cardCats = (card.dataset.categories || '').split('|');
        var matchesCat = cats.length === 0 || cats.some(function (c) { return cardCats.indexOf(c) !== -1; });
        var haystack = ((card.dataset.name || '') + ' ' + (card.dataset.country || '')).toLowerCase();
        var matchesSearch = q === '' || haystack.indexOf(q) !== -1;
        var show = matchesCat && matchesSearch;
        card.style.display = show ? '' : 'none';
        if (show) visible++;
      });
      if (emptyMsg) emptyMsg.style.display = visible === 0 ? 'block' : 'none';
    }

    if (allChip) {
      allChip.addEventListener('click', function () {
        catChips.forEach(function (c) { c.classList.remove('active'); });
        allChip.classList.add('active');
        applyFilters();
      });
    }
    catChips.forEach(function (chip) {
      chip.addEventListener('click', function () {
        if (allChip) allChip.classList.remove('active');
        chip.classList.toggle('active');
        if (activeCategories().length === 0 && allChip) allChip.classList.add('active');
        applyFilters();
      });
    });
    if (searchInput) searchInput.addEventListener('input', applyFilters);

    applyFilters();
  }
});
