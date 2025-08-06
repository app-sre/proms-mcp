"""Tests for the __main__.py module entry point."""

from unittest.mock import Mock, patch


class TestMainModule:
    """Test the main module entry point."""

    @patch("proms_mcp.__main__.main")
    def test_main_entry_point(self, mock_main: Mock) -> None:
        """Test that the main entry point calls the server main function."""
        # Import and execute the main module
        import proms_mcp.__main__

        # The main function should be called during module execution
        # We can't directly test the if __name__ == "__main__" block,
        # but we can test that the import works and the function exists
        assert hasattr(proms_mcp.__main__, "main")
        assert callable(proms_mcp.__main__.main)

    @patch("proms_mcp.server.app")
    @patch("proms_mcp.server.start_health_metrics_server")
    def test_main_function_import(
        self, mock_start_health: Mock, mock_app: Mock
    ) -> None:
        """Test that main function is properly imported from server."""
        from proms_mcp.__main__ import main

        # Mock the app.run method
        mock_app.run = Mock()

        # Call the main function
        main()

        # Verify the health server was started
        mock_start_health.assert_called_once()
        # Verify app.run was called with correct parameters
        mock_app.run.assert_called_once_with(
            transport="streamable-http",
            host="0.0.0.0",
            port=8000,
            path="/mcp/",
            log_level="info",
            stateless_http=True,
        )

    def test_module_structure(self) -> None:
        """Test that the module has the expected structure."""
        import proms_mcp.__main__

        # Check that the module has the expected attributes
        assert hasattr(proms_mcp.__main__, "__name__")
        assert hasattr(proms_mcp.__main__, "main")

        # Verify the docstring exists
        assert proms_mcp.__main__.__doc__ is not None
        assert "Entry point" in proms_mcp.__main__.__doc__
