"""Unit tests for ChatAttachmentHandler."""

from __future__ import annotations

import pytest

from lci_ignite.data.attachment_handler import ChatAttachmentHandler, UnsupportedFormatError
from lci_ignite.data.sources.easylca import EasyLCASource
from lci_ignite.data.sources.simapro_csv import SimaProCSVSource


class TestDetectFormat:
    def setup_method(self):
        self.handler = ChatAttachmentHandler()

    def test_detect_easylca(self, easylca_sample_path):
        assert self.handler.detect_format(str(easylca_sample_path)) == "easylca"

    def test_detect_easylca_minimal(self, easylca_minimal_path):
        assert self.handler.detect_format(str(easylca_minimal_path)) == "easylca"

    def test_detect_simapro(self, simapro_sample_path):
        assert self.handler.detect_format(str(simapro_sample_path)) == "simapro"

    def test_detect_simapro_process(self, simapro_process_path):
        assert self.handler.detect_format(str(simapro_process_path)) == "simapro"

    def test_detect_unknown_malformed(self, simapro_malformed_path):
        assert self.handler.detect_format(str(simapro_malformed_path)) == "unknown"

    def test_detect_unknown_missing_file(self):
        assert self.handler.detect_format("/nonexistent/file.csv") == "unknown"

    def test_detect_unknown_non_csv_extension(self, tmp_path):
        f = tmp_path / "data.xlsx"
        f.write_text("some content")
        assert self.handler.detect_format(str(f)) == "unknown"

    def test_detect_prefers_easylca_over_simapro(self, tmp_path):
        """If a file has both easyLCA columns and SimaPro markers, prefer easyLCA."""
        content = (
            "Process,Flow,Category,Amount,Unit,Direction\nProducts,Water,Resources,100,L,Input\n"
        )
        f = tmp_path / "ambiguous.csv"
        f.write_text(content)
        assert self.handler.detect_format(str(f)) == "easylca"


class TestCreateSource:
    def setup_method(self):
        self.handler = ChatAttachmentHandler()

    def test_create_easylca_source(self, easylca_sample_path):
        source = self.handler.create_source(str(easylca_sample_path))
        assert isinstance(source, EasyLCASource)

    def test_create_simapro_source(self, simapro_sample_path):
        source = self.handler.create_source(str(simapro_sample_path))
        assert isinstance(source, SimaProCSVSource)

    def test_create_source_raises_for_unknown(self, simapro_malformed_path):
        with pytest.raises(UnsupportedFormatError, match="Cannot detect CSV format"):
            self.handler.create_source(str(simapro_malformed_path))

    def test_create_source_raises_for_missing_file(self):
        with pytest.raises(UnsupportedFormatError):
            self.handler.create_source("/nonexistent/file.csv")

    def test_create_source_with_custom_encoding(self, easylca_sample_path):
        source = self.handler.create_source(str(easylca_sample_path), encoding="latin-1")
        assert isinstance(source, EasyLCASource)
        assert source._encoding == "latin-1"
