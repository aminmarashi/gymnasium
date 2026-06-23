// The ONE hardened markdown renderer, shared by every markdown surface in the
// app (article body, attached markdown, repo README and chat). Keeping a single
// renderer means the bracket-hardening and sanitization below apply everywhere.
//
// snarkdown handles the bulk of markdown. A focused pre/post-processing layer
// here handles the elements snarkdown cannot: it STASHES fenced + inline code
// (so brackets inside code are never mangled), <details>/<summary> collapsibles
// and GFM pipe tables, renders those itself, then lets snarkdown run on the
// remaining prose and finally restores the stashed HTML. All stashing uses a
// NUL-delimited sentinel (\x00B<idx>\x00) that snarkdown passes through
// untouched and that cannot collide with real content.
//
// Classic (non-module) script: exposes `window.MD`. Also supports CommonJS so
// Node tests can load it directly. Depends on `snarkdown` (window.snarkdown).
(function (root) {
  'use strict';

  // Strip <script> tags and inline on*= handlers from rendered markdown so an
  // attached file cannot self-XSS the authenticated origin (light safety).
  function sanitizeHTML(html) {
    return String(html)
      .replace(/<script[\s\S]*?<\/script\s*>/gi, '')
      .replace(/<script\b[^>]*>/gi, '')
      .replace(/\son\w+\s*=\s*"[^"]*"/gi, '')
      .replace(/\son\w+\s*=\s*'[^']*'/gi, '')
      .replace(/\son\w+\s*=\s*[^\s>]+/gi, '');
  }

  // snarkdown opens an <a> on a stray '[' and only closes it on a matching
  // ']'/'](url)'. Malformed input (e.g. a reversed arXiv watermark like
  // "]LC.sc[") therefore leaves a dangling <a> that swallows the rest of the
  // document into one runaway link. Neutralize this BEFORE snarkdown: protect
  // well-formed inline links/images, then escape every remaining '[' or ']' to
  // an HTML entity so no unbalanced bracket can ever start a link.
  //
  // The outer pipeline parks code/tables/details as \x00B<idx>\x00 sentinels
  // before calling this. Those carry a letter ('B') after the NUL, so this
  // function's own \x00<digits>\x00 stash never collides with them.
  function neutralizeStrayBrackets(md) {
    var kept = [];
    // Sentinel uses NUL, which never occurs in real markdown text (so it cannot
    // collide with content) and is fully resolved away before snarkdown runs.
    function stash(s) { kept.push(s); return '\x00' + (kept.length - 1) + '\x00'; }
    // Well-formed inline image/link: ![alt](url) or [text](url). The text/alt
    // and url may not themselves contain brackets, which keeps the match safe.
    var out = String(md).replace(/!?\[[^\[\]]*\]\([^()\s]*\)/g, stash);
    out = out.replace(/\[/g, '&#91;').replace(/\]/g, '&#93;');
    return out.replace(/\x00(\d+)\x00/g, function (_, i) { return kept[+i]; });
  }

  function escapeText(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  // --- inline markdown for table cells / details summaries ------------------
  // Cells contain inline markdown only; render them through the same hardened
  // path (bracket-neutralize -> snarkdown -> sanitize). snarkdown does not wrap
  // single lines in <p>, so the result is inline-safe. Any code sentinels the
  // text still carries pass straight through and are resolved by the outer
  // restore pass.
  function renderInline(text) {
    var safe = neutralizeStrayBrackets(String(text == null ? '' : text));
    var sd = root && root.snarkdown;
    var html = sd ? sd(safe) : escapeText(text);
    return sanitizeHTML(html);
  }

  // --- (a) fenced + inline code ---------------------------------------------
  // Render code ourselves with the text HTML-escaped (so brackets survive as
  // literal '[' / ']') instead of letting neutralizeStrayBrackets mangle them.
  // Preserve snarkdown's class convention so existing CSS keeps working.
  function stashCode(src, park) {
    // Fenced blocks first: ```lang\n...\n```
    var out = String(src).replace(/```[ \t]*(\w*)[ \t]*\n([\s\S]*?)```/g,
      function (_, lang, body) {
        body = body.replace(/\n$/, '');
        var cls = lang ? lang.toLowerCase() : '';
        var pre = '<pre class="code ' + cls + '"><code'
          + (cls ? ' class="language-' + cls + '"' : '')
          + '>' + escapeText(body) + '</code></pre>';
        // Own paragraph so snarkdown does not absorb it into surrounding prose.
        return '\n\n' + park(pre) + '\n\n';
      });
    // Inline `code` (whatever backticks remain after fenced blocks are gone).
    out = out.replace(/`([^`\n]+?)`/g, function (_, code) {
      return park('<code>' + escapeText(code) + '</code>');
    });
    return out;
  }

  // --- (b) <details>/<summary> collapsibles ----------------------------------
  // Author markdown may include raw GitHub-style collapsibles. Render the
  // summary and body markdown through expand() with the SAME shared `park`, so
  // any sentinels produced for code/tables/nested-details in the body keep
  // pointing at the one shared stash and are resolved by the single outer
  // restore. (A recursive renderMarkdownHTML call would allocate its own stash
  // yet reuse the same \x00B<idx>\x00 namespace, so an outer sentinel already
  // present in the body would resolve against the wrong array -> "undefined".)
  function stashDetails(src, park) {
    return String(src).replace(/<details\b[^>]*>([\s\S]*?)<\/details>/gi,
      function (_, inner) {
        var summary = '';
        var body = inner.replace(/<summary\b[^>]*>([\s\S]*?)<\/summary>/i,
          function (__, s) { summary = s; return ''; });
        var summaryHTML = expand(summary.trim(), park) || 'Details';
        var bodyHTML = expand(body.trim(), park);
        var html = '<details><summary>' + summaryHTML + '</summary>'
          + bodyHTML + '</details>';
        return '\n\n' + park(html) + '\n\n';
      });
  }

  // --- (c) GFM pipe tables ---------------------------------------------------
  function splitCells(line) {
    var t = String(line).trim().replace(/^\|/, '').replace(/\|$/, '');
    return t.split(/(?<!\\)\|/).map(function (c) {
      return c.replace(/\\\|/g, '|').trim();
    });
  }
  function isDelimRow(line) {
    if (String(line).indexOf('|') === -1) return false;
    var cells = splitCells(line);
    return cells.length > 0 && cells.every(function (c) {
      return /^:?-+:?$/.test(c);
    });
  }
  function isTableRow(line) {
    return String(line).indexOf('|') !== -1 && String(line).trim() !== '';
  }
  function alignOf(cell) {
    var l = cell.charAt(0) === ':';
    var r = cell.charAt(cell.length - 1) === ':';
    if (l && r) return 'center';
    if (r) return 'right';
    if (l) return 'left';
    return '';
  }
  function buildTable(header, delim, bodyLines) {
    var heads = splitCells(header);
    var aligns = splitCells(delim).map(alignOf);
    function styleAttr(i) {
      return aligns[i] ? ' style="text-align:' + aligns[i] + '"' : '';
    }
    var thead = '<thead><tr>' + heads.map(function (h, i) {
      return '<th' + styleAttr(i) + '>' + renderInline(h) + '</th>';
    }).join('') + '</tr></thead>';
    var tbody = '<tbody>' + bodyLines.map(function (row) {
      var cells = splitCells(row), tr = '';
      for (var k = 0; k < heads.length; k++) {
        tr += '<td' + styleAttr(k) + '>'
          + renderInline(k < cells.length ? cells[k] : '') + '</td>';
      }
      return '<tr>' + tr + '</tr>';
    }).join('') + '</tbody>';
    return '<table>' + thead + tbody + '</table>';
  }
  function stashTables(src, park) {
    var lines = String(src).split('\n');
    var out = [];
    var i = 0;
    while (i < lines.length) {
      if (isTableRow(lines[i]) && i + 1 < lines.length
          && isDelimRow(lines[i + 1])) {
        var header = lines[i], delim = lines[i + 1], body = [], j = i + 2;
        while (j < lines.length && isTableRow(lines[j])) { body.push(lines[j]); j++; }
        // Own paragraph so snarkdown leaves the sentinel standalone.
        out.push('', park(buildTable(header, delim, body)), '');
        i = j;
      } else {
        out.push(lines[i]);
        i++;
      }
    }
    return out.join('\n');
  }

  // One pipeline LEVEL: stash this level's code/details/tables into the shared
  // stash (via `park`), harden stray brackets, then snarkdown the remainder.
  // It does NOT restore or sanitize -- the public entry owns the single restore
  // + final sanitize so every level resolves against one shared stash. Called
  // both for the top-level document and (with the SAME park) for <details>
  // summary/body, so sentinels never cross stash boundaries.
  function expand(src, park) {
    src = stashCode(src, park);      // (a) code blocks must not be bracket-mangled
    src = stashDetails(src, park);   // (b) collapsibles (recurse via expand)
    src = stashTables(src, park);    // (c) GFM tables -> real <table>
    src = neutralizeStrayBrackets(src); // (d) harden stray brackets in prose

    var sd = root && root.snarkdown;
    return sd ? sd(src) : escapeText(src); // (e) snarkdown for the rest
  }

  function renderMarkdownHTML(md) {
    if (md == null) return '';
    var stash = [];
    // Letter prefix keeps these sentinels distinct from the digit-only stash
    // inside neutralizeStrayBrackets, so neither resolver touches the other's.
    function park(html) { stash.push(html); return '\x00B' + (stash.length - 1) + '\x00'; }

    var html = expand(String(md), park); // (a)-(e) over one shared stash

    // (f) restore stashes. Parked HTML may itself carry sentinels (e.g. a code
    // block nested inside a <details> body), so resolve repeatedly until none
    // remain. The guard bounds it against any pathological input.
    var guard = 0;
    while (/\x00B\d+\x00/.test(html) && guard++ < 1000) {
      html = html.replace(/\x00B(\d+)\x00/g, function (_, i) { return stash[+i]; });
    }

    return sanitizeHTML(html); // (g) sanitize once at the very end
  }

  var MD = {
    sanitizeHTML: sanitizeHTML,
    neutralizeStrayBrackets: neutralizeStrayBrackets,
    renderMarkdownHTML: renderMarkdownHTML
  };

  if (typeof module !== 'undefined' && module.exports) module.exports = MD;
  if (root) root.MD = MD;
})(typeof window !== 'undefined' ? window : (typeof global !== 'undefined' ? global : this));
