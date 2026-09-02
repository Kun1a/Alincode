from pathlib import Path

import pytest

from Alincode.web.attachments import load_attachments


def test_load_attachments_reads_utf8_text_and_keeps_the_file_name(tmp_path):
    source = tmp_path / "example.py"
    source.write_text("print('hello')\n", encoding="utf-8")

    attachments = load_attachments([str(source)])

    assert attachments == [(str(source.resolve()), "print('hello')\n")]


def test_load_attachments_rejects_a_file_larger_than_the_context_limit(tmp_path):
    source = tmp_path / "large.txt"
    source.write_bytes(b"x" * (200 * 1024 + 1))

    with pytest.raises(ValueError, match="200 KB"):
        load_attachments([str(source)])
