// The ONE hardened markdown renderer, shared by every markdown surface in the
// app (article body, attached markdown, repo README and chat). Keeping a single
// renderer means the bracket-hardening and sanitization below apply everywhere.
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

  function renderMarkdownHTML(md) {
    if (md == null) return '';
    var safe = neutralizeStrayBrackets(md);
    var sd = root && root.snarkdown;
    var html = sd ? sd(safe) : escapeText(md);
    return sanitizeHTML(html);
  }

  var MD = {
    sanitizeHTML: sanitizeHTML,
    neutralizeStrayBrackets: neutralizeStrayBrackets,
    renderMarkdownHTML: renderMarkdownHTML
  };

  if (typeof module !== 'undefined' && module.exports) module.exports = MD;
  if (root) root.MD = MD;
})(typeof window !== 'undefined' ? window : (typeof global !== 'undefined' ? global : this));
