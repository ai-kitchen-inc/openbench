"""Unit tests for LCIAGUIHandler."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from lci_ignite.server.handler import LCIAGUIHandler


class TestLCIAGUIHandlerInit:
    @patch("lci_ignite.server.handler.AGUIHandler.__init__", return_value=None)
    @patch("lci_ignite.server.handler.SQLiteMemoryStore")
    def test_init(self, mock_store_cls, mock_super_init):
        engine = MagicMock()
        LCIAGUIHandler(engine=engine, db_path="test.db")

        mock_super_init.assert_called_once_with(engine)
        mock_store_cls.assert_called_once_with(db_path="test.db")

    @patch("lci_ignite.server.handler.AGUIHandler.__init__", return_value=None)
    @patch("lci_ignite.server.handler.SQLiteMemoryStore")
    def test_default_db_path(self, mock_store_cls, mock_super_init):
        LCIAGUIHandler(engine=MagicMock())
        mock_store_cls.assert_called_once_with(db_path="lci_memory.db")


class TestLCIAGUIHandlerSessionTracking:
    @patch("lci_ignite.server.handler.AGUIHandler.__init__", return_value=None)
    @patch("lci_ignite.server.handler.AGUIHandler._get_or_create_session")
    @patch("lci_ignite.server.handler.SQLiteMemoryStore")
    def test_tracks_session_id(self, mock_store_cls, mock_super_session, mock_super_init):
        engine = MagicMock()
        handler = LCIAGUIHandler(engine=engine)
        mock_super_session.return_value = MagicMock()

        handler._get_or_create_session("session-123")

        assert handler._current_session_id == "session-123"
        mock_super_session.assert_called_once_with("session-123")
