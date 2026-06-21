"""Run the Node regression tests for the hardened markdown renderer (md.js).

These guard snarkdown's runaway-link bug: unbalanced brackets (e.g. a reversed
arXiv watermark like ``]LC.sc[``) must never open an <a> that swallows the rest
of the page. The actual assertions live in ``tests/js/test_markdown_render.mjs``
so they exercise the real browser ``window.MD.renderMarkdownHTML`` path; this
wrapper just drives Node from the normal pytest run (skipping if Node is absent).
"""

import shutil
import subprocess

import pytest

HERE = __import__("os").path.dirname(__file__)
SCRIPT = __import__("os").path.join(HERE, "js", "test_markdown_render.mjs")


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_markdown_renderer_hardening():
    result = subprocess.run(
        ["node", SCRIPT], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, (
        "node markdown tests failed:\n" + result.stdout + result.stderr)
    assert "checks passed" in result.stdout
