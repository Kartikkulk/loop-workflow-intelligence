"""Generated code must compile, keep the guard, and actually do the work.

The last of those is the point. A generator that emits plausible-looking source
is worth nothing; these tests run the file it produces against a real PDF and
check that a real file moved.
"""

from __future__ import annotations

import importlib.util
import py_compile
import subprocess
import sys
from pathlib import Path

import pytest

from app.services.codegen import SUPPORTED_METHODS, generate_code

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def _load_invoice_writer():
    """The PDF writer from the invoice generator, imported by path."""
    spec = importlib.util.spec_from_file_location(
        "_make_invoices", _SCRIPTS / "make_invoices.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.write_pdf


INVOICE_FLOW = [
    {"id": "s1", "type": "read", "connector": "files", "description": "read the invoice"},
    {"id": "s2", "type": "extract", "connector": "pdf", "description": "extract the total"},
    {"id": "s3", "type": "create", "connector": "files", "description": "file it away"},
    {"id": "s4", "type": "send", "connector": "jira", "description": "note it on the ticket"},
]
INVOICE_GUARDS = {"irreversible": ["s4"], "requires_approval_if": "amount > 1000000"}


def _generate(method: str, steps=None, guards=None):
    return generate_code(
        method=method,
        name="AWS invoice into filed archive",
        description="Generated in a test.",
        cluster_id="clu_test",
        steps=steps if steps is not None else INVOICE_FLOW,
        guards=guards if guards is not None else INVOICE_GUARDS,
    )


@pytest.mark.parametrize("method", SUPPORTED_METHODS)
def test_generated_source_compiles(method, tmp_path):
    """Whatever else is true of it, it has to be valid Python."""
    code = _generate(method)
    assert code is not None
    path = tmp_path / code.filename
    path.write_text(code.source, encoding="utf-8")
    py_compile.compile(str(path), doraise=True)


def test_n8n_has_no_source_file():
    """Its artefact is the workflow JSON, so it must not fake a script."""
    assert generate_code(
        method="n8n",
        name="x",
        description="",
        cluster_id="c",
        steps=INVOICE_FLOW,
        guards={},
    ) is None


def test_the_guard_survives_into_the_script():
    """A guard that does not reach the generated code protects nothing."""
    code = _generate("python")
    assert "amount > 1000000" in code.source
    assert "'s4'" in code.source or '"s4"' in code.source


def test_an_api_step_is_named_rather_than_stubbed():
    """An ungenerated step says what it needs; it never returns a fake success."""
    code = _generate("python")
    assert any("LOOP_JIRA" in caveat for caveat in code.caveats)


def test_playwright_refuses_to_run_on_placeholder_selectors():
    code = _generate("playwright")
    assert "NotConfigured" in code.source
    assert code.caveats, "placeholder selectors must be declared, not hidden"


def test_the_script_files_a_real_invoice(tmp_path):
    """End to end: generate the script, run it, and check a real file moved."""
    write_pdf = _load_invoice_writer()
    inbox = tmp_path / "Inbox"
    inbox.mkdir()
    invoice = inbox / "AWS-202601-0013-prod-platform.pdf"
    write_pdf(
        invoice,
        [
            "AMAZON WEB SERVICES EMEA SARL",
            "",
            "Invoice number   AWS-202601-0013",
            "Invoice date     2026-01-03",
            "Account          4471-8829-0013",
            "",
            # Under the 10,000-rupee guard, so the run is not held.
            "TOTAL DUE        INR 4,210.00",
        ],
    )

    # Only the local steps: the Jira step needs credentials a test must not have.
    code = _generate("python", steps=INVOICE_FLOW[:3], guards={"irreversible": []})
    script = tmp_path / code.filename
    script.write_text(code.source, encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(script), "--yes"],
        capture_output=True,
        text=True,
        env={"LOOP_FILES_ROOT": str(tmp_path), "PATH": "/usr/bin:/bin"},
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    assert not invoice.exists(), "the invoice should have been moved out of the inbox"
    filed = list((tmp_path / "Filed").rglob("*.pdf"))
    assert len(filed) == 1, f"expected one filed invoice, found {filed}"
    # Filed under the issuer and the invoice's own date, both read from the PDF.
    assert "Amazon Web Services" in str(filed[0])
    assert "2026" in str(filed[0]) and "01" in str(filed[0])


def test_the_guard_holds_an_expensive_invoice(tmp_path):
    """The same script, one digit larger, must stop instead of proceeding."""
    write_pdf = _load_invoice_writer()
    inbox = tmp_path / "Inbox"
    inbox.mkdir()
    write_pdf(
        inbox / "AWS-202601-0013-prod-platform.pdf",
        [
            "AMAZON WEB SERVICES EMEA SARL",
            "",
            "Invoice date     2026-01-03",
            # 42,100 rupees, well over the guard.
            "TOTAL DUE        INR 42,100.00",
        ],
    )

    code = _generate("python")
    script = tmp_path / code.filename
    script.write_text(code.source, encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(script), "--yes"],
        capture_output=True,
        text=True,
        env={"LOOP_FILES_ROOT": str(tmp_path), "PATH": "/usr/bin:/bin"},
        timeout=60,
    )
    assert "held for approval" in result.stdout
    assert "1 held for approval" in result.stdout
