// Regression tests for the ONE hardened markdown renderer (university/web/js/md.js).
//
// Focus: snarkdown opens an <a> on a stray '[' and only closes it on a matching
// ']'. A reversed arXiv watermark (e.g. "]LC.sc[" / unbalanced brackets) used to
// leave a dangling <a> that swallowed the rest of the page into one runaway blue
// link. The renderer must neutralize that while still rendering real markdown.
//
// Run standalone: `node tests/js/test_markdown_render.mjs`. Also driven from
// pytest (tests/test_markdown_js.py) so it runs in the normal suite.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import vm from 'node:vm';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB_JS = path.resolve(__dirname, '..', '..', 'university', 'web', 'js');

// Load the vendored snarkdown + md.js into a shared sandbox that emulates the
// browser globals each script expects (window for snarkdown, module for md.js).
const sandbox = { window: {}, module: { exports: {} } };
sandbox.global = sandbox;
vm.createContext(sandbox);
function load(rel) {
  vm.runInContext(readFileSync(path.join(WEB_JS, rel), 'utf8'), sandbox, { filename: rel });
}
load('vendor/snarkdown.js'); // sets window.snarkdown
load('md.js');               // sets window.MD (reads window.snarkdown)
const MD = sandbox.window.MD;

let passed = 0;
function check(name, fn) { fn(); passed += 1; console.log('  ok -', name); }

// --- the core regression: unbalanced brackets must NOT make a runaway link ---
check('"]x[" does not open a swallowing anchor', () => {
  const html = MD.renderMarkdownHTML(']x[ then a lot more text that must stay visible');
  // No anchor opened at all -> nothing to swallow the trailing text.
  assert.equal(html.includes('<a'), false, 'unbalanced brackets must not open <a>');
  assert.ok(html.includes('then a lot more text that must stay visible'));
});

check('reversed arXiv watermark line stays inert', () => {
  // The exact damage pattern seen in data/.../2606.19659/article.auto.md.
  const md = ']LC.sc[ 1v95691.6062:viXra\n\nReal **body** continues here.';
  const html = MD.renderMarkdownHTML(md);
  assert.equal(html.includes('<a'), false);
  assert.ok(html.includes('<strong>body</strong>'), 'real markdown after the junk still renders');
});

check('many unbalanced brackets never produce an anchor', () => {
  const html = MD.renderMarkdownHTML('a [ b [ c ] d ]] e [[[ f');
  assert.equal(html.includes('<a'), false);
  assert.ok(html.includes('f'));
});

// --- real markdown still renders correctly through the hardened path ---
check('well-formed link still becomes an anchor', () => {
  const html = MD.renderMarkdownHTML('see [the docs](https://example.com) please');
  assert.match(html, /<a href="https:\/\/example\.com">the docs<\/a>/);
});

check('lists, bold and headings render', () => {
  const html = MD.renderMarkdownHTML('# Title\n\n- one\n- two\n\nsome **bold** text');
  assert.ok(html.includes('<h1>Title</h1>'));
  assert.ok(html.includes('<ul>') && html.includes('<li>one</li>'));
  assert.ok(html.includes('<strong>bold</strong>'));
});

check('script/onerror sanitization still applies', () => {
  const html = MD.renderMarkdownHTML('hi <script>alert(1)</script> <img src=x onerror="boom()">');
  assert.equal(html.toLowerCase().includes('<script'), false);
  assert.equal(/onerror\s*=/i.test(html), false);
});

console.log(`\n${passed} markdown-render checks passed`);
