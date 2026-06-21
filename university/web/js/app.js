/* Gymnasium University — app shell, router and screens.
   Translated faithfully from GymApp.dc.html to vanilla JS. One fluid layout;
   the rail/tabs/panel-mode follow CSS media queries (matchMedia for the
   sheet/side panel + scrim). */
(function () {
  var S = window.State;
  var $ = function (id) { return document.getElementById(id); };

  // ---- tiny helpers --------------------------------------------------------
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }
  function ico(paths, attrs) {
    return '<svg viewBox="0 0 24 24" class="ico" ' + (attrs || '') + '>' + paths + '</svg>';
  }
  var ICON = {
    sun: '<circle cx="12" cy="12" r="4"></circle><path d="M12 2v2M12 20v2M4 12H2M22 12h-2M5 5l1.5 1.5M17.5 17.5 19 19M19 5l-1.5 1.5M6.5 17.5 5 19"></path>',
    moon: '<path d="M21 13a8 8 0 1 1-9.5-9 6.5 6.5 0 0 0 9.5 9z"></path>',
    back: '<path d="M15 6l-6 6 6 6"></path>',
    arrow: '<path d="M5 12h13M13 6l6 6-6 6"></path>',
    bookmark: '<path d="M6 4h12v16l-6-4-6 4V4z"></path>',
    spark: '<path d="M12 3l1.7 5.1L19 10l-5.3 1.9L12 17l-1.7-5.1L5 10l5.3-1.9z"></path>',
    link: '<path d="M10 13a5 5 0 0 0 7 0l2-2a5 5 0 0 0-7-7l-1 1"></path><path d="M14 11a5 5 0 0 0-7 0l-2 2a5 5 0 0 0 7 7l1-1"></path>',
    external: '<path d="M14 4h6v6"></path><path d="M20 4l-9 9"></path><path d="M19 14v5a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"></path>',
    search: '<circle cx="11" cy="11" r="7"></circle><path d="M21 21l-4-4"></path>',
    close: '<path d="M6 6l12 12M18 6L6 18"></path>',
    send: '<path d="M5 12h13M13 6l6 6-6 6"></path>',
    plus: '<path d="M12 5v14M5 12h14"></path>',
    check: '<path d="M5 12l4 4 10-10"></path>',
    chevron: '<path d="M6 9l6 6 6-6"></path>',
    refresh: '<path d="M21 12a9 9 0 1 1-2.6-6.4"></path><path d="M21 4v5h-5"></path>'
  };

  // ---- theme ---------------------------------------------------------------
  function applyTheme() {
    var app = $('app');
    if (S.theme === 'dark') app.classList.add('dark'); else app.classList.remove('dark');
    var light = S.theme === 'light';
    $('topbarThemeIcon').innerHTML = light ? ICON.moon : ICON.sun;
    var rti = $('railThemeIcon'); if (rti) rti.innerHTML = light ? ICON.moon : ICON.sun;
    var rtl = $('railThemeLabel'); if (rtl) rtl.textContent = light ? 'Dark' : 'Light';
  }
  function toggleTheme() { S.theme = S.theme === 'light' ? 'dark' : 'light'; S.saveTheme(); applyTheme(); }

  // ---- toast ---------------------------------------------------------------
  var toastTimer = null;
  function toast(msg) {
    var t = $('toast');
    t.innerHTML = ico(ICON.check, 'style="stroke:var(--grass-500);width:16px;height:16px"') + esc(msg);
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { t.hidden = true; }, 2400);
  }

  // ---- nav -----------------------------------------------------------------
  var SECTION = { papers: 'Papers', repos: 'Repos', reader: 'Reader', saved: 'Knowledge base', map: 'Knowledge map' };
  function kindFor(screen) { return screen === 'repos' ? 'repo' : 'paper'; }
  function setNavActive() {
    var screen = S.screen;
    document.querySelectorAll('.rail-nav[data-screen]').forEach(function (b) {
      b.classList.toggle('on', b.dataset.screen === screen);
    });
    document.querySelectorAll('.gym-tab[data-screen]').forEach(function (b) {
      b.classList.toggle('on', b.dataset.screen === screen);
    });
    $('topbarSection').textContent = SECTION[screen] || '';
  }
  function go(screen) {
    S.screen = screen;
    closePanel();
    render();
    $('scroll').scrollTop = 0;
  }

  // ====================================================================
  // FEED
  // ====================================================================
  function recency(iso) {
    if (!iso) return '';
    var then = new Date(iso); if (isNaN(then)) return '';
    var days = Math.floor((Date.now() - then.getTime()) / 86400000);
    if (days <= 0) return 'today';
    if (days < 7) return days + 'd ago';
    if (days < 30) return Math.floor(days / 7) + 'w ago';
    return Math.floor(days / 30) + 'mo ago';
  }
  function feedCard(item) {
    var kindLabel = item.kind === 'repo' ? 'Repo' : 'Paper';
    var why = S.density === 'comfort' && item.why
      ? '<p style="font:500 15px/1.55 var(--font-sans);color:var(--fg-2)">' + esc(item.why) + '</p>' : '';
    // Repo cards show stars + language; paper cards show the source line.
    var metaLeft;
    if (item.kind === 'repo') {
      var bits = [];
      if (item.stars != null) bits.push('★ ' + item.stars.toLocaleString());
      if (item.language) bits.push(esc(item.language));
      metaLeft = '<span style="font:600 12px/1.4 var(--font-sans);color:var(--fg-3)">' + (bits.join(' · ') || esc(item.source || '')) + '</span>';
    } else {
      metaLeft = '<span style="font:600 12px/1.4 var(--font-sans);color:var(--fg-3)">' + esc(item.source || '') + '</span>';
    }
    var ratingLabel = item.kind === 'repo' ? 'Stars' : 'Impact';
    return '' +
      '<article class="gym-card feed-card" data-id="' + item.id + '" style="background:var(--bg-surface);border:1px solid var(--border-hair);border-radius:14px;box-shadow:var(--shadow-1);padding:16px 18px;cursor:pointer;display:flex;flex-direction:column;gap:10px">' +
        '<div style="display:flex;align-items:center;gap:10px">' +
          '<span style="display:inline-flex;align-items:center;gap:6px;padding:3px 10px;border-radius:999px;font:700 11px/1.4 var(--font-sans);background:var(--spark-100);color:var(--spark-700)">' + kindLabel + '</span>' +
          metaLeft +
          '<span style="margin-left:auto;font:600 12px/1.4 var(--font-sans);color:var(--fg-muted)">' + esc(recency(item.published_at)) + '</span>' +
        '</div>' +
        '<h3 style="font:700 19px/1.3 var(--font-sans);color:var(--fg-1);letter-spacing:-.01em">' + esc(item.title) + '</h3>' +
        why +
        '<div style="display:flex;align-items:center;gap:12px;margin-top:2px">' +
          '<span style="font:700 12px/1 var(--font-sans);color:var(--fg-3);font-variant-numeric:tabular-nums">' + ratingLabel + ' ' + (item.signal || 0) + '</span>' +
          '<span style="position:relative;flex:1;max-width:140px;height:6px;border-radius:3px;background:var(--paper-200);overflow:hidden"><span style="position:absolute;left:0;top:0;bottom:0;width:' + (item.signal || 0) + '%;background:var(--spark-500);border-radius:3px"></span></span>' +
          '<span style="flex:1"></span>' +
          '<button class="gym-press feed-read btn-spark" data-id="' + item.id + '">Read' + ico(ICON.arrow, 'style="width:16px;height:16px;stroke-width:2.2"') + '</button>' +
        '</div>' +
      '</article>';
  }
  // Build one filter <select> from a facet list ({values:[{value,count}], capped}).
  function filterSelect(name, label, facet, current) {
    var opts = '<option value="">' + esc(label) + '</option>';
    var values = (facet && facet.values) || [];
    // Keep the active value selectable even if it fell outside the capped list.
    var present = false;
    values.forEach(function (v) {
      if (v.value === current) present = true;
      opts += '<option value="' + esc(v.value) + '"' + (v.value === current ? ' selected' : '') + '>' + esc(v.value) + ' (' + v.count + ')</option>';
    });
    if (current && !present) opts += '<option value="' + esc(current) + '" selected>' + esc(current) + '</option>';
    return '<select class="feed-filter" data-filter="' + name + '" style="height:38px;border:1.5px solid var(--border-default);background:var(--bg-input);color:var(--fg-1);border-radius:10px;padding:0 10px;font:500 14px/1 var(--font-sans);cursor:pointer;max-width:200px">' + opts + '</select>';
  }
  function renderFeed(kind) {
    var fs = S.feeds[kind];
    var isRepo = kind === 'repo';
    var title = isRepo ? 'Repos' : 'Papers';
    var blurb = isRepo
      ? 'Repositories from tracked labs. Search, filter and sort.'
      : 'Papers from the frontier labs. Search, filter and sort.';
    var cards = fs.items.length
      ? fs.items.map(feedCard).join('')
      : '<div style="text-align:center;padding:48px 24px;color:var(--fg-3);font:500 15px/1.5 var(--font-sans)">No items match. Try clearing the search or filters, or Refresh feed.</div>';
    var filters;
    if (isRepo) {
      filters = filterSelect('company', 'All companies', fs.facets && fs.facets.companies, fs.filters.company) +
                filterSelect('language', 'All languages', fs.facets && fs.facets.languages, fs.filters.language);
    } else {
      filters = filterSelect('author', 'All authors', fs.facets && fs.facets.authors, fs.filters.author) +
                filterSelect('company', 'All companies', fs.facets && fs.facets.companies, fs.filters.company) +
                filterSelect('publication', 'All publications', fs.facets && fs.facets.publications, fs.filters.publication);
    }
    return '' +
      '<div style="display:flex;align-items:flex-end;justify-content:space-between;gap:14px;flex-wrap:wrap;margin-bottom:16px">' +
        '<div>' +
          '<h1 style="font:700 32px/1.1 var(--font-display);letter-spacing:-.02em;color:var(--fg-1)">' + title + '</h1>' +
          '<p style="font:500 15px/1.5 var(--font-sans);color:var(--fg-3);margin-top:6px">' + blurb + '</p>' +
        '</div>' +
        '<div class="seg-row">' +
          '<button class="gym-seg' + (S.density === 'comfort' ? ' on' : '') + '" data-d="comfort">Comfort</button>' +
          '<button class="gym-seg' + (S.density === 'compact' ? ' on' : '') + '" data-d="compact">Compact</button>' +
        '</div>' +
      '</div>' +
      '<div style="position:relative;margin-bottom:12px">' +
        ico(ICON.search, 'style="position:absolute;left:13px;top:50%;transform:translateY(-50%);width:18px;height:18px;stroke:var(--ink-400);pointer-events:none"') +
        '<input class="gym-term-input" id="feedSearch" value="' + esc(fs.q) + '" placeholder="Search ' + (isRepo ? 'repos' : 'papers') + '…" style="padding-left:40px;height:46px" />' +
      '</div>' +
      '<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:18px">' +
        '<div class="seg-row">' +
          '<button class="gym-seg feed-sort' + (fs.sort === 'recency' ? ' on' : '') + '" data-sort="recency">Recency</button>' +
          '<button class="gym-seg feed-sort' + (fs.sort === 'rating' ? ' on' : '') + '" data-sort="rating">Rating</button>' +
        '</div>' +
        '<span style="flex:1"></span>' + filters +
      '</div>' +
      '<div style="display:flex;flex-direction:column;gap:14px">' + cards + '</div>';
  }

  // ====================================================================
  // READER
  // ====================================================================
  function termRegex() {
    var terms = (S.summaryTerms || []).slice();
    Object.keys(S.glossary || {}).forEach(function (t) { terms.push(t); });
    terms = terms.filter(function (t) { return t && t.length >= 3; });
    if (!terms.length) return null;
    // longest-first so multi-word terms win.
    terms.sort(function (a, b) { return b.length - a.length; });
    var escd = terms.map(function (t) { return t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); });
    return new RegExp('\\b(' + escd.join('|') + ')\\b', 'gi');
  }
  function paragraphHTML(text) {
    var re = termRegex();
    if (!re) return esc(text);
    var out = '', last = 0, m;
    while ((m = re.exec(text)) !== null) {
      out += esc(text.slice(last, m.index));
      out += '<span class="gym-term" data-term="' + esc(m[0]) + '">' + esc(m[0]) + '</span>';
      last = m.index + m[0].length;
      if (m.index === re.lastIndex) re.lastIndex++;
    }
    out += esc(text.slice(last));
    return out;
  }
  // The ONE hardened markdown renderer lives in md.js (window.MD) so the article
  // body, attached markdown, repo README and chat all share the same
  // bracket-hardening (against snarkdown's runaway-link bug) and <script>/on*=
  // sanitization. Fall back to escaped text if md.js somehow failed to load.
  function renderMarkdownHTML(md) {
    if (window.MD) return window.MD.renderMarkdownHTML(md);
    return esc(md);
  }
  function renderReader() {
    var it = S.item;
    if (!it) return '<p>Loading…</p>';
    var kindLabel = it.kind === 'repo' ? 'Repo' : 'Paper';
    var tags = (it.tags || []).map(function (t) {
      return '<span style="display:inline-flex;align-items:center;padding:3px 10px;border-radius:999px;font:600 11px/1.4 var(--font-sans);background:var(--paper-200);color:var(--fg-3)">' + esc(t) + '</span>';
    }).join('');
    var bodyHTML;
    if (it._markdownHTML != null) {
      // Markdown (uploaded or auto-converted) becomes the reader body (no
      // [[term]] re-marking). A small label shows where it came from.
      var srcLabel = it._markdownSource === 'user'
        ? 'Your uploaded markdown'
        : it._markdownSource === 'readme'
          ? 'README' : 'Auto-converted from the original';
      var labelHTML = '<div style="display:inline-flex;align-items:center;gap:6px;font:600 12px/1.3 var(--font-sans);color:var(--fg-muted);margin-bottom:14px">' + esc(srcLabel) + '</div>';
      bodyHTML = labelHTML + '<div class="gym-md" style="font:500 17px/1.7 var(--font-sans);color:var(--fg-1);max-width:64ch">' + it._markdownHTML + '</div>';
    } else if (it._markdownLoading) {
      bodyHTML = '<div style="display:flex;align-items:center;gap:8px;color:var(--fg-3);font:500 14px/1.5 var(--font-sans)">' + ico(ICON.refresh, 'class="ico spin" style="width:16px;height:16px"') + 'Converting the original to a readable view…</div>';
    } else {
      var bodyText = it.abstract || it.why || '';
      var paras = bodyText.split(/\n{2,}|\.\s{2,}/).filter(function (p) { return p.trim(); });
      if (!paras.length) paras = [bodyText];
      bodyHTML = paras.map(function (p) {
        return '<p style="font:500 18px/1.75 var(--font-sans);color:var(--fg-1);margin:0 0 20px;max-width:64ch">' + paragraphHTML(p.trim()) + '</p>';
      }).join('');
    }

    var summaryHTML;
    if (S.item._summary) {
      summaryHTML = S.item._summary.map(function (line) {
        return '<div style="display:flex;gap:10px;align-items:flex-start"><span style="margin-top:8px;width:6px;height:6px;border-radius:50%;background:var(--spark-500);flex:0 0 auto"></span><span style="font:500 16px/1.55 var(--font-sans);color:var(--fg-1)">' + esc(line) + '</span></div>';
      }).join('');
    } else {
      summaryHTML = '<div style="display:flex;align-items:center;gap:8px;color:var(--fg-3);font:500 14px/1.5 var(--font-sans)">' + ico(ICON.refresh, 'class="ico spin" style="width:16px;height:16px"') + 'Summarizing…</div>';
    }
    var modelLabel = esc(S.item._summaryModel ? S.modelName(S.item._summaryModel) : S.modelName());
    var docLink = '<a href="' + API.documentUrl(it.id) + '" target="_blank" rel="noopener" style="font:600 13px/1.3 var(--font-sans)">Open the stored document</a>';
    var origLink = it.url
      ? '<a href="' + esc(it.url) + '" target="_blank" rel="noopener noreferrer" style="font:600 13px/1.3 var(--font-sans);color:var(--fg-link);margin-left:10px">' + ico(ICON.external, 'style="width:14px;height:14px;vertical-align:-2px;margin-right:3px"') + 'Open original</a>'
      : '';
    var attachLabel = it.has_markdown ? 'Replace markdown' : 'Attach markdown';
    var attachControl = '<div style="margin-top:10px">' +
      '<button class="gym-press" id="mdAttachBtn" style="display:inline-flex;align-items:center;gap:6px;height:32px;padding:0 12px;border:1px solid var(--border-hair);background:var(--bg-surface);border-radius:999px;cursor:pointer;font:700 12px/1 var(--font-sans);color:var(--fg-2)">' + ico(ICON.plus, 'style="width:15px;height:15px"') + attachLabel + '</button>' +
      '<input type="file" id="mdFile" accept=".md,.markdown,text/markdown" hidden>' +
      '</div>';

    // A real <article> with a single <h1> title and <p>/markdown body lets
    // Safari detect the reading content and offer Reader Mode (a Safari UI
    // feature that cannot be automated). id=readBody stays here for selection.
    return '<article class="gym-read" id="readBody">' +
      '<button class="gym-press reader-back" style="display:inline-flex;align-items:center;gap:6px;height:34px;padding:0 12px 0 8px;border:none;background:none;color:var(--fg-3);cursor:pointer;font:600 14px/1 var(--font-sans);margin-bottom:12px;border-radius:8px">' + ico(ICON.back, 'style="width:18px;height:18px"') + (it.kind === 'repo' ? 'Repos' : 'Papers') + '</button>' +
      '<div style="display:flex;align-items:center;gap:8px;margin-bottom:12px;flex-wrap:wrap">' +
        '<span style="display:inline-flex;align-items:center;padding:3px 10px;border-radius:999px;font:700 11px/1.4 var(--font-sans);background:var(--spark-100);color:var(--spark-700)">' + kindLabel + '</span>' + tags +
      '</div>' +
      '<h1 style="font:700 31px/1.18 var(--font-display);letter-spacing:-.02em;color:var(--fg-1)">' + esc(it.title) + '</h1>' +
      '<p style="font:600 14px/1.5 var(--font-sans);color:var(--fg-3);margin-top:10px">' + esc(it.source || '') + ' · ' + docLink + origLink + '</p>' +
      attachControl +
      '<div style="background:var(--spark-100);border:1px solid var(--spark-200);border-radius:14px;padding:18px;margin:22px 0 26px">' +
        '<div style="display:flex;align-items:center;gap:8px;margin-bottom:12px">' +
          ico(ICON.spark, 'style="fill:var(--spark-500);stroke:none;width:18px;height:18px"') +
          '<span style="font:700 13px/1 var(--font-sans);color:var(--spark-700)">Readable summary</span>' +
          '<span style="margin-left:auto;font:600 11px/1 var(--font-sans);color:var(--fg-muted)">' + modelLabel + '</span>' +
        '</div>' +
        '<div style="display:flex;flex-direction:column;gap:10px">' + summaryHTML + '</div>' +
      '</div>' +
      '<button class="gym-press" id="chatArticleBtn" style="display:inline-flex;align-items:center;gap:8px;height:42px;padding:0 18px;border:none;background:var(--sky-500);color:#fff;border-radius:999px;cursor:pointer;font:700 14px/1 var(--font-sans);margin-bottom:18px">' +
        ico(ICON.send, 'style="width:17px;height:17px;stroke-width:2.2"') +
        'Chat about this article' +
      '</button>' +
      '<div style="display:inline-flex;align-items:center;gap:8px;padding:8px 12px;border-radius:999px;background:var(--sky-100);color:var(--sky-600);font:600 13px/1.3 var(--font-sans);margin-bottom:22px">' +
        ico('<path d="M4 7l5-3 6 3 5-2v12l-5 2-6-3-5 3z"></path>', 'style="width:16px;height:16px"') +
        'Select any text to explain, summarize, or ask — or tap an <span style="border-bottom:2px solid var(--spark-400);color:var(--spark-700)">underlined term</span>.' +
      '</div>' +
      bodyHTML +
    '</article>';
  }

  // ====================================================================
  // KNOWLEDGE BASE
  // ====================================================================
  function kbCard(e) {
    var def = e.lead && e.body ? (e.lead + ' — ' + e.body) : (e.body || e.lead || '');
    var srcName = e.source_title || e.source_url || 'source';
    var sourceBtn = e.item_id
      ? '<button class="gym-press kb-open" data-item="' + e.item_id + '" style="display:inline-flex;align-items:center;gap:6px;border:none;background:none;color:var(--fg-link);cursor:pointer;font:600 13px/1.3 var(--font-sans);padding:4px 0">' + ico(ICON.link, 'style="width:15px;height:15px"') + 'From: ' + esc(srcName) + '</button>'
      : '<span style="font:600 13px/1.3 var(--font-sans);color:var(--fg-muted)">From: ' + esc(srcName) + '</span>';
    var docLink = e.item_id
      ? '<a href="' + API.documentUrl(e.item_id) + '" target="_blank" rel="noopener" style="font:600 12px/1.3 var(--font-sans);margin-left:10px">document</a>' : '';
    return '<article style="background:var(--bg-surface);border:1px solid var(--border-hair);border-radius:14px;box-shadow:var(--shadow-1);padding:16px 18px;display:flex;flex-direction:column;gap:8px">' +
      '<div style="display:flex;align-items:center;gap:10px"><h3 style="font:700 18px/1.3 var(--font-sans);color:var(--fg-1)">' + esc(e.term) + '</h3><span style="margin-left:auto;display:inline-flex;align-items:center;padding:3px 10px;border-radius:999px;font:600 11px/1.4 var(--font-sans);background:var(--berry-100);color:var(--berry-600)">' + esc(e.tag || 'note') + '</span></div>' +
      '<p style="font:500 15px/1.6 var(--font-sans);color:var(--fg-2)">' + esc(def) + '</p>' +
      '<div style="display:flex;align-items:center;gap:8px;margin-top:4px;flex-wrap:wrap">' + sourceBtn + docLink +
        '<span style="margin-left:auto;font:600 12px/1.3 var(--font-sans);color:var(--fg-muted)">First seen ' + esc(recency(e.created_at) || 'just now') + '</span>' +
      '</div>' +
    '</article>';
  }
  function renderSaved() {
    var entries = S.kbEntries;
    var empty = entries.length === 0;
    var emptyBox = '';
    if (empty) {
      emptyBox = S.kbQuery
        ? '<div style="text-align:center;padding:48px 24px;background:var(--bg-surface);border:1px solid var(--border-hair);border-radius:16px"><p style="font:600 17px/1.4 var(--font-sans);color:var(--fg-2)">Nothing matches “' + esc(S.kbQuery) + '”.</p><p style="font:500 14px/1.5 var(--font-sans);color:var(--fg-3);margin-top:6px">Try a shorter word, or clear the search.</p></div>'
        : '<div style="text-align:center;padding:48px 24px;background:var(--bg-surface);border:1px solid var(--border-hair);border-radius:16px"><p style="font:600 17px/1.4 var(--font-sans);color:var(--fg-2)">Nothing saved yet.</p><p style="font:500 14px/1.5 var(--font-sans);color:var(--fg-3);margin-top:6px">Open a paper, select some text, and save what you learn.</p></div>';
    }
    return '<h1 style="font:700 32px/1.1 var(--font-display);letter-spacing:-.02em;color:var(--fg-1)">Knowledge base</h1>' +
      '<p style="font:500 15px/1.5 var(--font-sans);color:var(--fg-3);margin-top:6px">' + (S.kbCount != null ? S.kbCount : entries.length) + ' things you’ve learned. Each one links back to where you met it.</p>' +
      '<div style="position:relative;margin:18px 0 18px">' +
        ico(ICON.search, 'style="position:absolute;left:13px;top:50%;transform:translateY(-50%);width:18px;height:18px;stroke:var(--ink-400);pointer-events:none"') +
        '<input class="gym-term-input" id="kbSearch" value="' + esc(S.kbQuery) + '" placeholder="Search terms, definitions, sources…" style="padding-left:40px;height:46px" />' +
      '</div>' + emptyBox +
      '<div style="display:flex;flex-direction:column;gap:12px">' + entries.map(kbCard).join('') + '</div>';
  }

  // ====================================================================
  // KNOWLEDGE MAP
  // ====================================================================
  var TONE = { spark: 'var(--spark-500)', sky: 'var(--sky-500)', grass: 'var(--grass-500)', berry: 'var(--berry-500)', sun: 'var(--sun-500)', rose: 'var(--rose-600)' };
  function renderMap() {
    var d = S.mapData;
    var nodeById = {};
    d.nodes.forEach(function (n) { nodeById[n.id] = n; });
    var edges = d.edges.map(function (e) {
      var a = nodeById[e.src], b = nodeById[e.dst];
      if (!a || !b) return '';
      var col = e.source === 'ai' ? 'var(--sky-500)' : 'var(--paper-400)';
      var w = e.source === 'ai' ? 0.5 : 0.4;
      return '<line data-edge="' + e.id + '" x1="' + a.x + '" y1="' + a.y + '" x2="' + b.x + '" y2="' + b.y + '" stroke="' + col + '" stroke-width="' + w + '"></line>';
    }).join('');
    var nodes = d.nodes.map(function (n) {
      return '<div class="map-node" data-node="' + n.id + '" style="left:' + n.x + '%;top:' + n.y + '%"><span class="map-dot" style="background:' + (TONE[n.tone] || TONE.spark) + '"></span>' + esc(n.label) + '</div>';
    }).join('');
    var empty = d.nodes.length === 0
      ? '<div style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:var(--fg-3);font:500 15px/1.5 var(--font-sans);text-align:center;padding:24px">Save terms in the knowledge base and they appear here automatically.</div>' : '';
    return '<h1 style="font:700 32px/1.1 var(--font-display);letter-spacing:-.02em;color:var(--fg-1)">Knowledge map</h1>' +
      '<p style="font:500 15px/1.5 var(--font-sans);color:var(--fg-3);margin-top:6px">Concepts you’ve met, linked by what explains what. Drag to rearrange; draw a link, or let AI suggest them.</p>' +
      '<div class="map-stage" id="mapStage">' +
        '<svg class="map-edges" viewBox="0 0 100 100" preserveAspectRatio="none">' + edges + '</svg>' + nodes + empty +
      '</div>' +
      '<div class="map-controls">' +
        '<button class="btn-ghost" id="mapLinkBtn">' + ico(ICON.link, 'style="width:15px;height:15px"') + 'Link two concepts</button>' +
        '<button class="btn-spark" id="mapAiBtn">' + ico(ICON.spark, 'style="width:16px;height:16px;fill:#fff;stroke:none"') + 'AI-suggested links</button>' +
        '<span id="mapLinkHint" style="font:600 12px/1.3 var(--font-sans);color:var(--fg-muted)"></span>' +
      '</div>' +
      '<div class="map-hint">' + ico(ICON.link, 'style="width:15px;height:15px"') + 'Tip: with “Link” active, tap two nodes to connect them. Tap a line to remove it.</div>';
  }

  // ====================================================================
  // CONVERSATION PANEL
  // ====================================================================
  function modeLabel() {
    return S.mode === 'summarize' ? 'Summary' : S.mode === 'ask' ? 'Ask a follow-up' : 'Explain simply';
  }
  function modelMenuHTML() {
    var provs = (S.models.providers || []);
    return provs.map(function (g) {
      var items = (g.models || []).map(function (m) {
        var on = m.id === S.model;
        return '<button class="gym-nav model-pick" data-id="' + esc(m.id) + '" style="display:flex;align-items:center;gap:8px;border:none;background:none;cursor:pointer;border-radius:8px;padding:9px 10px;font:600 14px/1 var(--font-sans);color:var(--fg-1);text-align:left;min-height:40px;width:100%">' +
          (on ? ico(ICON.check, 'style="width:16px;height:16px;stroke:var(--grass-600);stroke-width:2.6"') : '<span style="width:16px;flex:0 0 auto"></span>') +
          esc(m.name) + '</button>';
      }).join('');
      return '<div style="font:700 10px/1 var(--font-sans);letter-spacing:.08em;text-transform:uppercase;color:var(--fg-muted);padding:9px 10px 5px">' + esc(g.name) + '</div>' + items;
    }).join('');
  }
  function renderChatPanel() {
    var thread = S.thread.map(function (m) {
      if (m.role === 'user') {
        return '<div style="align-self:flex-end;max-width:86%;background:var(--sky-500);color:#fff;padding:10px 14px;border-radius:14px 14px 4px 14px;font:500 15px/1.5 var(--font-sans);white-space:pre-wrap">' + esc(m.content) + '</div>';
      }
      // Assistant answers come back as markdown — render them through the same
      // hardened renderer the article body uses so lists/bold/code/headings show.
      return '<div class="gym-md" style="align-self:flex-start;max-width:90%;background:var(--paper-200);color:var(--fg-1);padding:10px 14px;border-radius:14px 14px 14px 4px;font:500 15px/1.6 var(--font-sans)">' + renderMarkdownHTML(m.content) + '</div>';
    }).join('');
    var grounded = '';
    var g = S.chatGrounded;
    if (g && ((g.notes && g.notes.length) || (g.concepts && g.concepts.length))) {
      var parts = [];
      var n = (g.notes || []).length;
      if (n) parts.push('Grounded in ' + n + ' note' + (n === 1 ? '' : 's') + ' from your knowledge base');
      if (g.concepts && g.concepts.length) parts.push('concepts: ' + g.concepts.join(', '));
      grounded = '<div class="chat-grounded" style="align-self:flex-start;display:flex;align-items:center;gap:6px;font:600 12px/1.5 var(--font-sans);color:var(--fg-muted)">' +
        ico(ICON.spark, 'style="fill:var(--spark-500);stroke:none;width:14px;height:14px;flex:0 0 auto"') +
        '<span>' + esc(parts.join(' · ')) + '</span></div>';
    }
    var loading = S.busy
      ? '<div style="align-self:flex-start;display:flex;align-items:center;gap:8px;color:var(--fg-3);font:500 14px/1.5 var(--font-sans)">' + ico(ICON.refresh, 'class="ico spin" style="width:16px;height:16px"') + 'Thinking…</div>' : '';
    var empty = (!thread && !loading)
      ? '<div style="color:var(--fg-3);font:500 15px/1.6 var(--font-sans)">Ask anything about this article. Answers draw on your saved notes and concept map.</div>' : '';
    var menu = S.modelMenuOpen
      ? '<div style="position:absolute;right:0;top:40px;z-index:50;width:250px;max-height:340px;overflow:auto;background:var(--bg-surface);border:1px solid var(--border-default);border-radius:12px;box-shadow:var(--shadow-3);padding:6px;display:flex;flex-direction:column;gap:2px" class="gym-scroll">' + modelMenuHTML() + '</div>' : '';
    var title = S.item ? S.item.title : 'this article';
    return '' +
      (S.isDesktop() ? '' : '<div style="display:flex;justify-content:center;padding:9px 0 2px"><div style="width:38px;height:4px;border-radius:2px;background:var(--paper-400)"></div></div>') +
      '<div style="display:flex;align-items:center;gap:8px;padding:12px 14px 12px 16px;border-bottom:1px solid var(--border-hair);flex:0 0 auto">' +
        '<span style="font:700 16px/1.2 var(--font-sans);color:var(--fg-1)">Chat about this article</span>' +
        '<div style="position:relative;margin-left:auto">' +
          '<button class="gym-press" id="modelBtn" style="display:inline-flex;align-items:center;gap:7px;height:34px;padding:0 10px;border:1px solid var(--border-hair);background:var(--bg-surface);border-radius:999px;cursor:pointer;font:700 12px/1 var(--font-sans);color:var(--fg-2)"><span style="width:7px;height:7px;border-radius:50%;background:var(--grass-500);flex:0 0 auto"></span>' + esc(S.modelName()) + ico(ICON.chevron, 'style="width:14px;height:14px;stroke-width:2.4"') + '</button>' + menu +
        '</div>' +
        '<button class="gym-press" id="panelClose" aria-label="Close" style="display:inline-flex;align-items:center;justify-content:center;width:34px;height:34px;border:none;background:var(--paper-200);border-radius:9px;cursor:pointer;color:var(--fg-2)">' + ico(ICON.close, 'style="width:17px;height:17px;stroke-width:2.2"') + '</button>' +
      '</div>' +
      '<div class="gym-scroll" id="chatScroll" style="flex:1;min-height:0;overflow:auto;padding:16px;display:flex;flex-direction:column;gap:12px">' +
        '<div style="font:600 12px/1.5 var(--font-sans);color:var(--fg-muted)">About: “' + esc(title) + '”</div>' +
        empty + thread + loading + grounded +
      '</div>' +
      '<div style="border-top:1px solid var(--border-hair);padding:12px 14px;display:flex;flex-direction:column;gap:10px;flex:0 0 auto">' +
        '<div style="display:flex;gap:8px;align-items:center">' +
          '<input class="gym-term-input" id="panelDraft" value="' + esc(S.draft) + '" placeholder="Ask about this article…" />' +
          '<button class="gym-press" id="panelSend" aria-label="Send" style="display:inline-flex;align-items:center;justify-content:center;width:46px;height:46px;flex:0 0 auto;border:none;background:var(--sky-500);color:#fff;border-radius:10px;cursor:pointer">' + ico(ICON.send, 'style="width:19px;height:19px;stroke-width:2.2"') + '</button>' +
        '</div>' +
      '</div>';
  }
  function renderPanel() {
    if (S.chatMode) return renderChatPanel();
    var a = S.answer || { lead: '', body: '', analogy: null };
    var analogy = a.analogy
      ? '<div style="display:flex;gap:9px;align-items:flex-start;padding:11px 13px;border-radius:10px;background:var(--sky-100);font:500 14px/1.55 var(--font-sans);color:var(--fg-1)"><span style="font-weight:700;color:var(--sky-600);white-space:nowrap">Picture it</span><span>' + esc(a.analogy) + '</span></div>' : '';
    var thread = S.thread.map(function (m) {
      if (m.role === 'user') {
        return '<div style="align-self:flex-end;max-width:86%;background:var(--sky-500);color:#fff;padding:10px 14px;border-radius:14px 14px 4px 14px;font:500 15px/1.5 var(--font-sans)">' + esc(m.content) + '</div>';
      }
      // Markdown answer -> hardened renderer (same path as the article body).
      return '<div class="gym-md" style="align-self:flex-start;max-width:90%;background:var(--paper-200);color:var(--fg-1);padding:10px 14px;border-radius:14px 14px 14px 4px;font:500 15px/1.6 var(--font-sans)">' + renderMarkdownHTML(m.content) + '</div>';
    }).join('');
    var savedConfirm = S.justSaved
      ? '<div style="display:flex;align-items:center;gap:9px;padding:11px 13px;border-radius:10px;background:var(--grass-100);color:var(--grass-600);font:600 14px/1.4 var(--font-sans)">' + ico(ICON.check, 'style="width:17px;height:17px;stroke-width:2.6"') + 'Saved to your knowledge base.<button class="gym-press panel-gosaved" style="margin-left:auto;border:none;background:none;color:var(--fg-link);cursor:pointer;font:700 14px/1 var(--font-sans)">Open</button></div>' : '';
    var loading = S.busy && !S.answer
      ? '<div style="display:flex;align-items:center;gap:8px;color:var(--fg-3);font:500 14px/1.5 var(--font-sans)">' + ico(ICON.refresh, 'class="ico spin" style="width:16px;height:16px"') + 'Thinking…</div>' : '';
    var menu = S.modelMenuOpen
      ? '<div style="position:absolute;right:0;top:40px;z-index:50;width:250px;max-height:340px;overflow:auto;background:var(--bg-surface);border:1px solid var(--border-default);border-radius:12px;box-shadow:var(--shadow-3);padding:6px;display:flex;flex-direction:column;gap:2px" class="gym-scroll">' + modelMenuHTML() + '</div>' : '';

    return '' +
      (S.isDesktop() ? '' : '<div style="display:flex;justify-content:center;padding:9px 0 2px"><div style="width:38px;height:4px;border-radius:2px;background:var(--paper-400)"></div></div>') +
      '<div style="display:flex;align-items:center;gap:8px;padding:12px 14px 12px 16px;border-bottom:1px solid var(--border-hair);flex:0 0 auto">' +
        '<span style="font:700 16px/1.2 var(--font-sans);color:var(--fg-1)">' + modeLabel() + '</span>' +
        '<div style="position:relative;margin-left:auto">' +
          '<button class="gym-press" id="modelBtn" style="display:inline-flex;align-items:center;gap:7px;height:34px;padding:0 10px;border:1px solid var(--border-hair);background:var(--bg-surface);border-radius:999px;cursor:pointer;font:700 12px/1 var(--font-sans);color:var(--fg-2)"><span style="width:7px;height:7px;border-radius:50%;background:var(--grass-500);flex:0 0 auto"></span>' + esc(S.modelName()) + ico(ICON.chevron, 'style="width:14px;height:14px;stroke-width:2.4"') + '</button>' + menu +
        '</div>' +
        '<button class="gym-press" id="panelClose" aria-label="Close" style="display:inline-flex;align-items:center;justify-content:center;width:34px;height:34px;border:none;background:var(--paper-200);border-radius:9px;cursor:pointer;color:var(--fg-2)">' + ico(ICON.close, 'style="width:17px;height:17px;stroke-width:2.2"') + '</button>' +
      '</div>' +
      '<div class="gym-scroll" style="flex:1;min-height:0;overflow:auto;padding:16px;display:flex;flex-direction:column;gap:14px">' +
        '<div style="display:flex;align-items:flex-start;gap:8px;flex-wrap:wrap"><span style="font:600 12px/1.7 var(--font-sans);color:var(--fg-muted)">From the text</span><span style="display:inline-block;padding:5px 11px;border-radius:9px;background:var(--sun-100);color:var(--ink-900);font:600 13px/1.4 var(--font-sans);max-width:100%">“' + esc(S.selText) + '”</span></div>' +
        '<div class="seg-row"><button class="gym-seg' + (S.mode === 'explain' ? ' on' : '') + '" data-mode="explain">Explain simply</button><button class="gym-seg' + (S.mode === 'summarize' ? ' on' : '') + '" data-mode="summarize">Summarize</button></div>' +
        '<div style="background:var(--bg-surface);border:1px solid var(--border-hair);border-radius:14px;padding:16px 18px;display:flex;flex-direction:column;gap:10px">' +
          (loading || (
            '<div style="font:700 19px/1.35 var(--font-display);letter-spacing:-.01em;color:var(--fg-1)">' + esc(a.lead) + '</div>' +
            '<div class="gym-md" style="font:500 16px/1.7 var(--font-sans);color:var(--fg-2)">' + renderMarkdownHTML(a.body) + '</div>' + analogy)) +
        '</div>' +
        thread + savedConfirm +
      '</div>' +
      '<div style="border-top:1px solid var(--border-hair);padding:12px 14px;display:flex;flex-direction:column;gap:10px;flex:0 0 auto">' +
        '<div style="display:flex;gap:8px;align-items:center">' +
          '<input class="gym-term-input" id="panelDraft" value="' + esc(S.draft) + '" placeholder="Ask a follow-up…" />' +
          '<button class="gym-press" id="panelSend" aria-label="Send" style="display:inline-flex;align-items:center;justify-content:center;width:46px;height:46px;flex:0 0 auto;border:none;background:var(--sky-500);color:#fff;border-radius:10px;cursor:pointer">' + ico(ICON.send, 'style="width:19px;height:19px;stroke-width:2.2"') + '</button>' +
        '</div>' +
        '<button class="gym-press" id="panelSave" style="display:inline-flex;align-items:center;justify-content:center;gap:8px;height:46px;border:none;background:var(--spark-500);color:#fff;border-radius:10px;cursor:pointer;font:700 15px/1 var(--font-sans)">' + ico(ICON.plus, 'style="width:18px;height:18px;stroke-width:2.2"') + (S.savedEntryId ? 'Saved' : 'Save to knowledge base') + '</button>' +
      '</div>';
  }
  function syncPanel() {
    var panel = $('panel'), scrim = $('scrim');
    if (!S.panelOpen) { panel.hidden = true; scrim.hidden = true; return; }
    panel.classList.remove('sheet', 'side');
    panel.classList.add(S.isDesktop() ? 'side' : 'sheet');
    panel.hidden = false;
    scrim.hidden = S.isDesktop();
    panel.innerHTML = renderPanel();
  }

  // ====================================================================
  // RENDER + ROUTER
  // ====================================================================
  function render() {
    setNavActive();
    var host = $('screen');
    if (S.screen === 'papers' || S.screen === 'repos') host.innerHTML = renderFeed(kindFor(S.screen));
    else if (S.screen === 'reader') host.innerHTML = renderReader();
    else if (S.screen === 'saved') host.innerHTML = renderSaved();
    else if (S.screen === 'map') { host.innerHTML = renderMap(); wireMap(); }
    syncPanel();
  }

  // ---- hash router ---------------------------------------------------------
  // Hash-based so it works against the static file server with no backend
  // change. Routes: #/papers[?q&sort&author&company&publication],
  // #/repos[?q&sort&company&language], #/read/<id>, #/saved[?q=...], #/map.
  // #/ or #/feed (legacy) fall through to #/papers.
  var FEED_PARAMS = {
    paper: ['q', 'sort', 'author', 'company', 'publication'],
    repo: ['q', 'sort', 'company', 'language']
  };
  function parseHash() {
    var raw = location.hash || '';
    if (raw.charAt(0) === '#') raw = raw.slice(1);
    var query = '';
    var qi = raw.indexOf('?');
    if (qi !== -1) { query = raw.slice(qi + 1); raw = raw.slice(0, qi); }
    var parts = raw.split('/').filter(Boolean);
    var seg = parts[0] || '';
    var sp; try { sp = new URLSearchParams(query); } catch (e) { sp = new URLSearchParams(''); }
    if (seg === 'read') {
      return { screen: 'reader', id: parts[1] ? parseInt(parts[1], 10) : null };
    }
    if (seg === 'papers' || seg === 'repos') {
      var kind = kindFor(seg);
      var filters = {};
      FEED_PARAMS[kind].forEach(function (k) {
        if (k === 'q' || k === 'sort') return;
        filters[k] = sp.get(k) || '';
      });
      return {
        screen: seg, kind: kind,
        q: sp.get('q') || '',
        sort: sp.get('sort') === 'rating' ? 'rating' : 'recency',
        filters: filters
      };
    }
    if (seg === 'saved') {
      return { screen: 'saved', q: sp.get('q') || '' };
    }
    if (seg === 'map') return { screen: 'map' };
    return { screen: 'papers', kind: 'paper', q: '', sort: 'recency', filters: {} };
  }
  function buildHash(screen, opts) {
    opts = opts || {};
    if (screen === 'reader') return '#/read/' + opts.id;
    if (screen === 'saved') return '#/saved' + (opts.q ? '?q=' + encodeURIComponent(opts.q) : '');
    if (screen === 'map') return '#/map';
    // papers / repos: serialize this feed's q + sort + active filters.
    var kind = kindFor(screen);
    var fs = S.feeds[kind];
    var q = [];
    if (fs.q) q.push('q=' + encodeURIComponent(fs.q));
    if (fs.sort && fs.sort !== 'recency') q.push('sort=' + encodeURIComponent(fs.sort));
    Object.keys(fs.filters).forEach(function (k) {
      if (fs.filters[k]) q.push(k + '=' + encodeURIComponent(fs.filters[k]));
    });
    return '#/' + screen + (q.length ? '?' + q.join('&') : '');
  }
  // Real in-app navigation: push a history entry (or replace it) and apply.
  // Setting location.hash fires hashchange, which is where the route is
  // actually applied — so Back/Forward and address-bar edits behave the same.
  function navigate(screen, opts, replace) {
    var h = buildHash(screen, opts);
    if (replace) { history.replaceState(null, '', h); applyRoute(); return; }
    if (location.hash === h) { applyRoute(); return; }  // hashchange won't fire
    location.hash = h;
  }
  function applyRoute() {
    var r = parseHash();
    if (r.screen === 'reader') {
      if (r.id == null || isNaN(r.id)) { navigate('papers', null, true); return; }
      openReader(r.id);
      return;
    }
    if (r.screen === 'saved') {
      S.kbQuery = r.q || '';
      go('saved');
      runKbSearch(S.kbQuery, false);
      return;
    }
    if (r.screen === 'map') { go('map'); loadMap(); return; }
    // papers / repos: hydrate this feed's state from the hash, then query.
    var fs = S.feeds[r.kind];
    fs.q = r.q;
    fs.sort = r.sort;
    Object.keys(fs.filters).forEach(function (k) { fs.filters[k] = (r.filters[k] || ''); });
    S.readerReturn = location.hash || ('#/' + r.screen);
    go(r.screen);
    if (!fs.facets) loadFacets(r.kind);
    loadFeed(r.kind);
  }

  // ====================================================================
  // BEHAVIOUR
  // ====================================================================
  // -- feeds (papers / repos) --
  function feedParams(kind) {
    var fs = S.feeds[kind];
    var p = { q: fs.q, sort: fs.sort, limit: 60 };
    Object.keys(fs.filters).forEach(function (k) { if (fs.filters[k]) p[k] = fs.filters[k]; });
    return p;
  }
  function loadFeed(kind) {
    return API.feed(kind, feedParams(kind)).then(function (res) {
      S.feeds[kind].items = res.items || [];
      if (S.screen === (kind === 'repo' ? 'repos' : 'papers')) render();
    }).catch(function () {});
  }
  function loadFacets(kind) {
    return API.facets(kind).then(function (f) {
      S.feeds[kind].facets = f;
      if (S.screen === (kind === 'repo' ? 'repos' : 'papers')) render();
    }).catch(function () {});
  }
  // Live search: reflect the query in the URL (replaceState so typing doesn't
  // spam Back/Forward), debounce the query, and re-render keeping caret/focus.
  var feedTimer = null;
  function onFeedSearch(kind, v) {
    S.feeds[kind].q = v;
    history.replaceState(null, '', buildHash(kind === 'repo' ? 'repos' : 'papers'));
    clearTimeout(feedTimer);
    feedTimer = setTimeout(function () {
      API.feed(kind, feedParams(kind)).then(function (res) {
        S.feeds[kind].items = res.items || [];
        if (S.screen !== (kind === 'repo' ? 'repos' : 'papers')) return;
        var input = $('feedSearch');
        var pos = input ? input.selectionStart : null;
        $('screen').innerHTML = renderFeed(kind);
        var ni = $('feedSearch');
        if (ni) { ni.focus(); if (pos != null) try { ni.setSelectionRange(pos, pos); } catch (e) {} }
      }).catch(function () {});
    }, 220);
  }

  function openReader(id) {
    S.screen = 'reader';
    S.item = null; S.summaryTerms = [];
    render();
    API.item(id).then(function (it) {
      S.item = it;
      S.summaryTerms = it.summary_terms || [];
      if (it.summary_readable) { it._summary = it.summary_readable; }
      // Try to load markdown when one exists OR an original could be converted.
      // The first open may trigger a lazy auto-conversion server-side, so show
      // a small loading state until it resolves (404 falls back to abstract).
      if (it.has_markdown || it.markdown_available) { it._markdownLoading = true; }
      render();
      if (it.has_markdown || it.markdown_available) {
        API.markdown(id).then(function (md) {
          if (S.item && S.item.id === id) {
            S.item._markdownLoading = false;
            if (md != null) {
              S.item._markdownHTML = renderMarkdownHTML(md.text);
              S.item._markdownSource = md.source;
            }
            render();
          }
        }).catch(function () {
          if (S.item && S.item.id === id) { S.item._markdownLoading = false; render(); }
        });
      }
      if (!it.summary_readable) {
        API.summarize(id, S.model).then(function (res) {
          if (S.item && S.item.id === id) {
            S.item._summary = res.summary;
            S.item._summaryModel = res.model;
            S.summaryTerms = res.terms || S.summaryTerms;
            render();
          }
        }).catch(function () {});
      } else {
        it._summaryModel = S.model;
      }
    }).catch(function (e) { toast('Could not open item'); });
  }

  function attachMarkdown(file) {
    if (!file || !S.item) return;
    var id = S.item.id;
    API.uploadMarkdown(id, file).then(function () {
      toast('Markdown attached');
      return API.markdown(id);
    }).then(function (md) {
      if (S.item && S.item.id === id && md != null) {
        S.item.has_markdown = true;
        S.item._markdownLoading = false;
        S.item._markdownHTML = renderMarkdownHTML(md.text);
        S.item._markdownSource = md.source;  // 'user' — upload overrides auto.
        render();
      }
    }).catch(function () { toast('Could not attach markdown'); });
  }

  // -- selection toolbar --
  function hideToolbar() { $('toolbar').hidden = true; S.affordance = null; }
  function onSelect() {
    if (S.screen !== 'reader' || S.panelOpen) return;
    var sel = window.getSelection && window.getSelection();
    if (!sel || sel.isCollapsed || sel.rangeCount === 0) { hideToolbar(); return; }
    var text = sel.toString().replace(/\s+/g, ' ').trim();
    if (text.length < 2) { hideToolbar(); return; }
    var readEl = $('readBody');
    var range = sel.getRangeAt(0);
    if (!readEl || !readEl.contains(range.commonAncestorContainer)) return;
    var r = range.getBoundingClientRect();
    var root = $('col').getBoundingClientRect();
    S.selText = text;
    var tb = $('toolbar');
    tb.style.left = (r.left - root.left + r.width / 2) + 'px';
    tb.style.top = Math.max(8, r.top - root.top) + 'px';
    tb.hidden = false;
  }

  function openPanel(span, mode) {
    S.panelOpen = true; S.chatMode = false; S.selText = span; S.mode = mode;
    S.answer = null; S.thread = []; S.draft = '';
    S.savedEntryId = null; S.justSaved = false; S.busy = true; S.modelMenuOpen = false;
    hideToolbar();
    try { window.getSelection().removeAllRanges(); } catch (e) {}
    syncPanel();
    askServer(mode, null);
  }
  // -- article chat (whole-article, knowledge-grounded) --
  function openChat() {
    if (!S.item) return;
    var id = S.item.id;
    S.panelOpen = true; S.chatMode = true; S.modelMenuOpen = false;
    S.thread = []; S.draft = ''; S.chatGrounded = null; S.chatEntryId = null;
    S.busy = true;
    hideToolbar();
    try { window.getSelection().removeAllRanges(); } catch (e) {}
    syncPanel();
    API.chatThread(id).then(function (res) {
      if (!S.chatMode || !S.item || S.item.id !== id) return;
      S.busy = false;
      S.chatEntryId = res.kb_entry_id || null;
      S.thread = (res.messages || []).map(function (m) {
        return { role: m.role, content: m.content };
      });
      syncPanel();
    }).catch(function () { S.busy = false; syncPanel(); });
  }
  function sendChat() {
    var q = (S.draft || '').trim(); if (!q || !S.item) return;
    var id = S.item.id;
    S.draft = '';
    S.thread.push({ role: 'user', content: q });
    S.busy = true; syncPanel();
    API.chat({ item_id: id, message: q, model: S.model }).then(function (res) {
      if (!S.chatMode || !S.item || S.item.id !== id) return;
      S.busy = false;
      S.chatEntryId = res.kb_entry_id || S.chatEntryId;
      S.thread.push({ role: 'assistant', content: answerText(res.answer) });
      S.chatGrounded = res.grounded || null;
      syncPanel();
    }).catch(function () { S.busy = false; toast('Chat failed'); syncPanel(); });
  }
  function askServer(mode, message) {
    var payload = {
      span_text: S.selText, mode: mode, model: S.model,
      item_id: S.item ? S.item.id : null
    };
    if (S.savedEntryId) payload.kb_entry_id = S.savedEntryId;
    if (message) payload.message = message;
    S.busy = true;
    return API.ask(payload).then(function (res) {
      S.busy = false;
      if (message) {
        S.thread.push({ role: 'user', content: message });
        S.thread.push({ role: 'assistant', content: answerText(res.answer) });
      } else {
        S.answer = res.answer;
      }
      syncPanel();
    }).catch(function () { S.busy = false; toast('AI request failed'); syncPanel(); });
  }
  function answerText(a) {
    var parts = [a.lead, a.body];
    if (a.analogy) parts.push('Picture it: ' + a.analogy);
    return parts.filter(Boolean).join('\n');
  }
  function setMode(mode) {
    S.mode = mode; S.answer = null; S.busy = true; syncPanel();
    askServer(mode, null);
  }
  function send() {
    var q = (S.draft || '').trim(); if (!q) return;
    S.draft = ''; S.mode = 'ask';
    askServer('ask', q);
  }
  function closePanel() {
    S.panelOpen = false; S.chatMode = false; S.modelMenuOpen = false;
    hideToolbar(); syncPanel();
  }
  function saveEntry() {
    if (!S.answer || S.savedEntryId) return;
    var payload = {
      span_text: S.selText, item_id: S.item ? S.item.id : null,
      mode: S.mode, model: S.model, answer: S.answer, thread: S.thread
    };
    API.kbSave(payload).then(function (res) {
      S.savedEntryId = res.entry.id;
      S.justSaved = true;
      toast('Saved to your knowledge base');
      syncPanel();
      loadGlossary();
    }).catch(function () { toast('Save failed'); });
  }

  // -- knowledge base search (debounced) --
  var kbTimer = null;
  // Fetch results for the current query and re-render the saved screen.
  // inPlace keeps caret/focus in the search box (live typing); a full render
  // is used when the route is applied (deep link / Back-Forward restore).
  function runKbSearch(q, inPlace) {
    var query = (q || '').trim();
    var p = query ? API.kbSearch(query) : API.kb();
    return p.then(function (res) {
      S.kbEntries = res.entries || [];
      if (!query) S.kbCount = S.kbEntries.length;
      if (S.screen !== 'saved') return;
      if (inPlace) renderInPlaceSaved(); else render();
    });
  }
  function onKbSearch(v) {
    S.kbQuery = v;
    // Reflect the query in the URL as the user types, but replace the current
    // history entry so typing does not spam Back/Forward.
    history.replaceState(null, '', buildHash('saved', { q: v }));
    clearTimeout(kbTimer);
    kbTimer = setTimeout(function () { runKbSearch(v, true); }, 220);
  }
  function renderInPlaceSaved() {
    // Re-render saved screen but keep focus in the search box.
    var input = $('kbSearch');
    var pos = input ? input.selectionStart : null;
    $('screen').innerHTML = renderSaved();
    var ni = $('kbSearch');
    if (ni) { ni.focus(); if (pos != null) try { ni.setSelectionRange(pos, pos); } catch (e) {} }
  }
  function loadGlossary() {
    API.kb().then(function (res) {
      S.glossary = {};
      (res.entries || []).forEach(function (e) { if (e.term) S.glossary[e.term.toLowerCase()] = e.id; });
    });
  }

  // -- map interactions --
  var linkMode = false, linkFirst = null, dragState = null;
  function loadMap() { API.map().then(function (d) { S.mapData = d; if (S.screen === 'map') render(); }); }
  function wireMap() {
    linkFirst = null;
    var stage = $('mapStage');
    if (!stage) return;
    var linkBtn = $('mapLinkBtn'), aiBtn = $('mapAiBtn'), hint = $('mapLinkHint');
    if (linkBtn) linkBtn.classList.toggle('on', linkMode);
    function setHint() {
      hint.textContent = linkMode ? (linkFirst ? 'Pick the second concept…' : 'Pick the first concept…') : '';
    }
    setHint();
    if (linkBtn) linkBtn.addEventListener('click', function () {
      linkMode = !linkMode; linkFirst = null;
      linkBtn.classList.toggle('on', linkMode);
      document.querySelectorAll('.map-node').forEach(function (n) { n.classList.remove('linking'); });
      setHint();
    });
    if (aiBtn) aiBtn.addEventListener('click', function () {
      aiBtn.disabled = true; aiBtn.innerHTML = '<svg viewBox="0 0 24 24" class="ico spin" style="width:16px;height:16px;stroke:#fff">' + ICON.refresh + '</svg>Asking AI…';
      API.mapAiLinks(S.model).then(function (r) {
        toast(r.added ? ('Added ' + r.added + ' link' + (r.added === 1 ? '' : 's')) : 'No new links found');
        loadMap();
      }).catch(function () { toast('AI links failed'); loadMap(); });
    });
    // edges: tap to delete
    stage.querySelectorAll('line[data-edge]').forEach(function (ln) {
      ln.style.cursor = 'pointer'; ln.style.strokeWidth = '0.8';
      ln.addEventListener('click', function () {
        var id = ln.getAttribute('data-edge');
        API.mapEdgeDelete(id).then(function () { toast('Link removed'); loadMap(); });
      });
    });
    // nodes: drag or link
    stage.querySelectorAll('.map-node').forEach(function (node) {
      node.addEventListener('pointerdown', function (ev) {
        if (linkMode) return; // linking handled on click
        ev.preventDefault();
        var rect = stage.getBoundingClientRect();
        dragState = { node: node, id: node.getAttribute('data-node'), rect: rect, moved: false };
        node.setPointerCapture(ev.pointerId);
        node.classList.add('dragging');
      });
      node.addEventListener('pointermove', function (ev) {
        if (!dragState || dragState.node !== node) return;
        dragState.moved = true;
        var rect = dragState.rect;
        var x = ((ev.clientX - rect.left) / rect.width) * 100;
        var y = ((ev.clientY - rect.top) / rect.height) * 100;
        x = Math.max(3, Math.min(97, x)); y = Math.max(4, Math.min(96, y));
        node.style.left = x + '%'; node.style.top = y + '%';
        dragState.x = x; dragState.y = y;
        updateEdgesFor(dragState.id, x, y);
      });
      node.addEventListener('pointerup', function (ev) {
        if (linkMode) return; // linking handled on click (single path)
        if (!dragState || dragState.node !== node) return;
        node.classList.remove('dragging');
        if (dragState.moved && dragState.x != null) {
          API.mapPosition(dragState.id, dragState.x, dragState.y).catch(function () {});
        }
        dragState = null;
      });
      node.addEventListener('click', function () { if (linkMode) handleLinkClick(node); });
    });
    function handleLinkClick(node) {
      var id = node.getAttribute('data-node');
      if (!linkFirst) {
        linkFirst = id; node.classList.add('linking'); setHint();
        return;
      }
      if (linkFirst === id) { node.classList.remove('linking'); linkFirst = null; setHint(); return; }
      API.mapEdgeAdd(linkFirst, id).then(function () {
        toast('Linked'); linkFirst = null; loadMap();
      }).catch(function () { toast('Could not link'); linkFirst = null; loadMap(); });
    }
  }
  function updateEdgesFor(nodeId, x, y) {
    var stage = $('mapStage'); if (!stage) return;
    stage.querySelectorAll('line[data-edge]').forEach(function (ln) {
      S.mapData.edges.forEach(function (e) {
        if (String(e.id) !== ln.getAttribute('data-edge')) return;
        if (String(e.src) === String(nodeId)) { ln.setAttribute('x1', x); ln.setAttribute('y1', y); }
        if (String(e.dst) === String(nodeId)) { ln.setAttribute('x2', x); ln.setAttribute('y2', y); }
      });
    });
  }

  // ====================================================================
  // EVENT WIRING (delegation)
  // ====================================================================
  function wireGlobal() {
    $('topbarTheme').addEventListener('click', toggleTheme);
    $('railTheme').addEventListener('click', toggleTheme);

    document.querySelectorAll('[data-screen]').forEach(function (b) {
      if (b.dataset.screen === 'refresh-trigger') return;
      b.addEventListener('click', function () { navigate(b.dataset.screen); });
    });
    $('railRefresh').addEventListener('click', triggerRefresh);

    // Browser Back/Forward (and address-bar hash edits) re-apply the route.
    window.addEventListener('hashchange', applyRoute);

    // Screen-level delegation.
    $('screen').addEventListener('click', function (e) {
      var sortBtn = e.target.closest('.feed-sort[data-sort]');
      if (sortBtn) {
        var sk = kindFor(S.screen);
        S.feeds[sk].sort = sortBtn.dataset.sort;
        navigate(S.screen);
        return;
      }
      var card = e.target.closest('.feed-card, .feed-read');
      if (card) {
        var id = card.getAttribute('data-id');
        if (id) { S.readerReturn = location.hash; navigate('reader', { id: parseInt(id, 10) }); return; }
      }
      var seg = e.target.closest('.gym-seg[data-d]');
      if (seg) { S.density = seg.dataset.d; render(); return; }
      var back = e.target.closest('.reader-back');
      if (back) {
        if (S.readerReturn && location.hash !== S.readerReturn) location.hash = S.readerReturn;
        else navigate('papers');
        return;
      }
      var mdBtn = e.target.closest('#mdAttachBtn');
      if (mdBtn) { var inp = $('mdFile'); if (inp) inp.click(); return; }
      if (e.target.closest('#chatArticleBtn')) { openChat(); return; }
      var term = e.target.closest('.gym-term');
      if (term) { openPanel(term.getAttribute('data-term'), 'explain'); return; }
      var kbOpen = e.target.closest('.kb-open');
      if (kbOpen) { navigate('reader', { id: parseInt(kbOpen.getAttribute('data-item'), 10) }); return; }
    });
    $('screen').addEventListener('input', function (e) {
      if (e.target.id === 'kbSearch') onKbSearch(e.target.value);
      else if (e.target.id === 'feedSearch') onFeedSearch(kindFor(S.screen), e.target.value);
    });
    $('screen').addEventListener('change', function (e) {
      if (e.target.id === 'mdFile' && e.target.files && e.target.files[0]) {
        attachMarkdown(e.target.files[0]);
        e.target.value = '';
      }
      var filt = e.target.closest && e.target.closest('.feed-filter');
      if (filt) {
        var fk = kindFor(S.screen);
        S.feeds[fk].filters[filt.getAttribute('data-filter')] = filt.value;
        navigate(S.screen);
      }
    });

    // Reader text selection.
    var scroll = $('scroll');
    scroll.addEventListener('mouseup', onSelect);
    scroll.addEventListener('touchend', onSelect);

    // Toolbar.
    $('toolbar').addEventListener('click', function (e) {
      var b = e.target.closest('button[data-mode]');
      if (b) openPanel(S.selText, b.dataset.mode);
    });

    // Scrim closes panel.
    $('scrim').addEventListener('click', closePanel);

    // Panel delegation (panel re-renders, so delegate on the container).
    $('panel').addEventListener('click', function (e) {
      if (e.target.closest('#panelClose')) { closePanel(); return; }
      if (e.target.closest('#modelBtn')) { S.modelMenuOpen = !S.modelMenuOpen; syncPanel(); return; }
      var pick = e.target.closest('.model-pick');
      if (pick) { S.model = pick.getAttribute('data-id'); S.modelMenuOpen = false; syncPanel(); return; }
      var seg = e.target.closest('.gym-seg[data-mode]');
      if (seg) { setMode(seg.dataset.mode); return; }
      if (e.target.closest('#panelSend')) { S.chatMode ? sendChat() : send(); return; }
      if (e.target.closest('#panelSave')) { saveEntry(); return; }
      if (e.target.closest('.panel-gosaved')) { closePanel(); navigate('saved'); return; }
    });
    $('panel').addEventListener('input', function (e) {
      if (e.target.id === 'panelDraft') S.draft = e.target.value;
    });
    $('panel').addEventListener('keydown', function (e) {
      if (e.target.id === 'panelDraft' && e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        S.chatMode ? sendChat() : send();
      }
    });

    // Re-sync panel mode on viewport change.
    window.matchMedia('(min-width: 901px)').addListener(function () { if (S.panelOpen) syncPanel(); });
  }

  // -- refresh --
  var refreshPoll = null;
  function triggerRefresh() {
    API.refresh(null, 7).then(function (st) {
      toast('Refreshing the feed…');
      pollRefresh();
    }).catch(function () { toast('Could not start refresh'); });
  }
  function pollRefresh() {
    clearInterval(refreshPoll);
    refreshPoll = setInterval(function () {
      API.refreshStatus().then(function (st) {
        if (st.status === 'done') {
          clearInterval(refreshPoll);
          toast('Feed updated');
          // Re-pull both feeds' facets and the active feed's items.
          loadFacets('paper'); loadFacets('repo');
          if (S.screen === 'papers' || S.screen === 'repos') loadFeed(kindFor(S.screen));
        } else if (st.status === 'error') {
          clearInterval(refreshPoll);
          toast('Refresh failed');
        }
      }).catch(function () { clearInterval(refreshPoll); });
    }, 2000);
  }

  // ====================================================================
  // BOOT
  // ====================================================================
  function boot() {
    applyTheme();
    wireGlobal();

    API.me().then(function (me) {
      S.user = me;
      $('railUserName').textContent = me.username;
      $('railAvatar').textContent = (me.username || '?').charAt(0);
      // Apply the current hash as a deep link once authenticated. A direct
      // #/read/<id> visit fetches the item via openReader, so cold loads work.
      applyRoute();
    }).catch(function () {});

    API.models().then(function (m) {
      S.models = m;
      S.model = m.default || (m.providers[0] && m.providers[0].models[0] && m.providers[0].models[0].id) || null;
    }).catch(function () {});

    loadGlossary();
    render();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
