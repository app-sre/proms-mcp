"""Unit tests for authentication configuration."""

import os
from unittest.mock import patch

from proms_mcp.auth import AuthMode
from proms_mcp.config import get_auth_mode


def test_get_auth_mode_default() -> None:
    """Test get_auth_mode returns NONE by default."""
    with patch.dict(os.environ, {}, clear=True):
        auth_mode = get_auth_mode()
        assert auth_mode == AuthMode.NONE


def test_get_auth_mode_none() -> None:
    """Test get_auth_mode with AUTH_MODE=none."""
    with patch.dict(os.environ, {"AUTH_MODE": "none"}):
        auth_mode = get_auth_mode()
        assert auth_mode == AuthMode.NONE


def test_get_auth_mode_active() -> None:
    """Test get_auth_mode with AUTH_MODE=active."""
    with patch.dict(os.environ, {"AUTH_MODE": "active"}):
        auth_mode = get_auth_mode()
        assert auth_mode == AuthMode.ACTIVE


def test_get_auth_mode_case_insensitive() -> None:
    """Test get_auth_mode is case insensitive."""
    with patch.dict(os.environ, {"AUTH_MODE": "NONE"}):
        auth_mode = get_auth_mode()
        assert auth_mode == AuthMode.NONE

    with patch.dict(os.environ, {"AUTH_MODE": "Active"}):
        auth_mode = get_auth_mode()
        assert auth_mode == AuthMode.ACTIVE


def test_get_auth_mode_invalid_defaults_to_none() -> None:
    """Test get_auth_mode defaults to NONE for invalid values."""
    with patch.dict(os.environ, {"AUTH_MODE": "invalid"}):
        auth_mode = get_auth_mode()
        assert auth_mode == AuthMode.NONE
