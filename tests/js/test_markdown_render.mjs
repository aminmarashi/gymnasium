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

// --- new: code blocks render literally, brackets intact ----------------------
check('fenced code block keeps brackets and is not a link', () => {
  const md = '```js\nconst x = arr[0] + a[i];\n```';
  const html = MD.renderMarkdownHTML(md);
  assert.ok(html.includes('<pre'), 'fenced block renders as <pre>');
  assert.ok(html.includes('<code'), 'fenced block renders <code>');
  assert.ok(html.includes('arr[0]'), 'literal brackets survive (no &#91;)');
  assert.ok(html.includes('a[i]'));
  assert.equal(html.includes('&#91;'), false, 'brackets in code not entity-escaped');
  assert.equal(html.includes('<a'), false, 'code brackets do not open an anchor');
});

check('fenced code keeps language class convention', () => {
  const html = MD.renderMarkdownHTML('```python\nprint(1)\n```');
  assert.ok(html.includes('class="code python"'));
  assert.ok(html.includes('class="language-python"'));
});

check('inline code with brackets renders intact', () => {
  const html = MD.renderMarkdownHTML('use `code with [brackets]` inline');
  assert.match(html, /<code>code with \[brackets\]<\/code>/);
  assert.equal(html.includes('<a'), false);
});

// --- new: GFM pipe tables ----------------------------------------------------
check('GFM table renders thead/tbody with alignment and inline markdown', () => {
  const md = [
    '| Name | Score | Note |',
    '| :--- | :---: | ---: |',
    '| **Ada** | 99 | see `x` |',
    '| Bob | 50 | [doc](https://e.com) |',
  ].join('\n');
  const html = MD.renderMarkdownHTML(md);
  assert.ok(html.includes('<table>'), 'renders a <table>');
  assert.ok(html.includes('<thead>') && html.includes('<tbody>'));
  assert.ok(html.includes('<th'), 'header cells use <th>');
  assert.ok(html.includes('<td'), 'body cells use <td>');
  assert.ok(/<th[^>]*style="text-align:center"[^>]*>Score<\/th>/.test(html),
    'center alignment applied to header');
  assert.ok(/style="text-align:right"/.test(html), 'right alignment present');
  assert.ok(html.includes('<strong>Ada</strong>'), 'inline bold inside a cell');
  assert.ok(html.includes('<code>x</code>'), 'inline code inside a cell');
  assert.ok(html.includes('<a href="https://e.com">doc</a>'), 'link inside a cell');
});

check('pipes inside a fenced code block are not turned into a table', () => {
  const md = '```\n| a | b |\n| - | - |\n| 1 | 2 |\n```';
  const html = MD.renderMarkdownHTML(md);
  assert.equal(html.includes('<table'), false, 'code-fenced pipes stay as code');
  assert.ok(html.includes('| a | b |'));
});

// --- new: <details>/<summary> collapsibles ----------------------------------
check('details/summary renders with inner markdown', () => {
  const md = '<details><summary>Title</summary>\n\nbody **bold**</details>';
  const html = MD.renderMarkdownHTML(md);
  assert.ok(html.includes('<details>'), 'renders <details>');
  assert.ok(html.includes('<summary>'), 'renders <summary>');
  assert.ok(html.includes('Title'), 'summary text preserved');
  assert.ok(html.includes('<strong>bold</strong>'), 'inner markdown rendered');
});

check('details strips script/on*= but keeps the disclosure', () => {
  const md = '<details><summary>S</summary>\n\nhi <script>alert(1)</script>'
    + ' <img src=x onerror="boom()"></details>';
  const html = MD.renderMarkdownHTML(md);
  assert.ok(html.includes('<details>'));
  assert.equal(html.toLowerCase().includes('<script'), false);
  assert.equal(/onerror\s*=/i.test(html), false);
});

// --- new: code/tables/details nested INSIDE a <details> body ----------------
// Regression: the body of a <details> used to be rendered by a recursive
// renderMarkdownHTML that allocated its own stash but reused the same
// \x00B<idx>\x00 sentinel namespace, so an outer code/table sentinel parked
// before stashDetails resolved against the wrong array and rendered as the
// literal text "undefined". A single shared stash fixes it.
check('fenced code block inside <details> renders <pre><code>, not "undefined"', () => {
  const md = '<details><summary>S</summary>\n\n```js\nconst x = arr[0];\n```\n</details>';
  const html = MD.renderMarkdownHTML(md);
  assert.ok(html.includes('<details>'), 'renders <details>');
  assert.ok(html.includes('<pre'), 'fenced block renders as <pre>');
  assert.ok(html.includes('<code'), 'fenced block renders <code>');
  assert.ok(html.includes('arr[0]'), 'literal brackets survive inside the code');
  assert.equal(html.includes('undefined'), false, 'sentinel must not resolve to "undefined"');
});

check('GFM table inside <details> renders <table>/<th>/<td>', () => {
  const md = [
    '<details><summary>Data</summary>',
    '',
    '| A | B |',
    '| - | - |',
    '| 1 | 2 |',
    '',
    '</details>',
  ].join('\n');
  const html = MD.renderMarkdownHTML(md);
  assert.ok(html.includes('<details>'), 'renders <details>');
  assert.ok(html.includes('<table>'), 'renders a <table>');
  assert.ok(html.includes('<th'), 'header cells use <th>');
  assert.ok(html.includes('<td'), 'body cells use <td>');
  assert.equal(html.includes('undefined'), false, 'no stray "undefined"');
});

check('inline `code` inside a <details> body renders <code>', () => {
  const md = '<details><summary>S</summary>\n\nuse `arr[0]` here</details>';
  const html = MD.renderMarkdownHTML(md);
  assert.ok(html.includes('<details>'), 'renders <details>');
  assert.match(html, /<code>arr\[0\]<\/code>/);
  assert.equal(html.includes('undefined'), false, 'no stray "undefined"');
});

check('nested <details> inside a <details> renders both disclosures', () => {
  const md = '<details><summary>Outer</summary>\n\n'
    + '<details><summary>Inner</summary>\n\nbody **bold**</details>\n\n</details>';
  const html = MD.renderMarkdownHTML(md);
  assert.equal(html.match(/<details>/g).length, 2, 'two <details> elements');
  assert.equal(html.match(/<summary>/g).length, 2, 'two <summary> elements');
  assert.ok(html.includes('Outer') && html.includes('Inner'), 'both summaries present');
  assert.ok(html.includes('<strong>bold</strong>'), 'inner body markdown rendered');
  assert.equal(html.includes('undefined'), false, 'no stray "undefined"');
});

console.log(`\n${passed} markdown-render checks passed`);
