// News page: Substack feed rendering (SPEC.md Section 6.5 / 7.2).
// Reads posts from the Cloudflare Worker feed proxy (workers/substack-feed/)
// once it's deployed and NEWS_FEED_ENDPOINT is set in build.py. Until then
// (or if the fetch fails) the grid stays empty and the spec's own empty
// state -- "News is on its way. Sign up to hear first." -- shows instead,
// so there is nothing to fake here: this file either renders real posts or
// gets out of the way.
document.addEventListener('DOMContentLoaded', function () {
  var grid = document.getElementById('newsGrid');
  var emptyMsg = document.getElementById('newsEmpty');
  var loadMoreBtn = document.getElementById('newsLoadMore');
  if (!grid) return;

  var endpoint = grid.dataset.feedEndpoint;
  if (!endpoint) return; // empty state (already visible) stands as-is

  var PAGE_SIZE = 9;
  var shown = 0;
  var posts = [];

  function formatDate(iso) {
    if (!iso) return '';
    var d = new Date(iso);
    if (isNaN(d.getTime())) return '';
    return d.toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' });
  }

  function renderCard(post) {
    var card = document.createElement('div');
    card.className = 'news-card';
    var coverHtml = post.image
      ? '<img class="cover" src="' + post.image + '" alt="" loading="lazy">'
      : '<div class="placeholder-img"><span>Sauna for All</span></div>';
    card.innerHTML = coverHtml +
      '<div class="news-card-body">' +
        '<h3>' + escapeHtml(post.title || '') + '</h3>' +
        '<div class="meta">' + escapeHtml(formatDate(post.date)) + '</div>' +
        '<p class="small muted">' + escapeHtml(post.summary || '') + '</p>' +
        '<a href="' + post.link + '" target="_blank" rel="noopener" style="font-weight:700; text-decoration:underline; font-size:0.9rem;">Read more &rarr;</a>' +
      '</div>';
    return card;
  }

  function escapeHtml(s) {
    var div = document.createElement('div');
    div.textContent = s;
    return div.innerHTML;
  }

  function showMore() {
    var next = posts.slice(shown, shown + PAGE_SIZE);
    next.forEach(function (post) { grid.appendChild(renderCard(post)); });
    shown += next.length;
    if (loadMoreBtn) loadMoreBtn.style.display = shown < posts.length ? 'inline-block' : 'none';
  }

  fetch(endpoint)
    .then(function (r) { return r.json(); })
    .then(function (data) {
      posts = (data && data.posts) || [];
      if (posts.length === 0) return; // build-time cards stay as they are
      // Cards are rendered at build time too, so clear them first rather than
      // appending a second copy of every post.
      grid.innerHTML = '';
      shown = 0;
      if (emptyMsg) emptyMsg.style.display = 'none';
      showMore();
    })
    .catch(function () {
      // Feed unreachable -- leave the empty state showing rather than
      // surface a broken/blank section.
    });

  if (loadMoreBtn) loadMoreBtn.addEventListener('click', showMore);
});
