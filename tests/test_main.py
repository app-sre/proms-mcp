"""Tests for the __main__.py module entry point."""

from unittest.mock import Mock, patch


class TestMainModule:
    """Test the main module entry point."""

    @patch("promesh_mcp.__main__.main")
    def test_main_entry_point(self, mock_main: Mock) -> None:
        """Test that the main entry point calls the server main function."""
        # Import and execute the main module
        import promesh_mcp.__main__

        # The main function should be called during module execution
        # We can't directly test the if __name__ == "__main__" block,
        # but we can test that the import works and the function exists
        assert hasattr(promesh_mcp.__main__, "main")
        assert callable(promesh_mcp.__main__.main)

    @patch("uvicorn.run")
    @patch("promesh_mcp.server.start_health_metrics_server")
    def test_main_function_import(
        self, mock_start_health: Mock, mock_uvicorn_run: Mock
    ) -> None:
        """Test that main function is properly imported from server."""
        from promesh_mcp.__main__ import main

        # Call the main function
        main()

        # Verify the health server was started
        mock_start_health.assert_called_once()
        # Verify uvicorn.run was called
        mock_uvicorn_run.assert_called_once()

    def test_module_structure(self) -> None:
        """Test that the module has the expected structure."""
        import promesh_mcp.__main__

        # Check that the module has the expected attributes
        assert hasattr(promesh_mcp.__main__, "__name__")
        assert hasattr(promesh_mcp.__main__, "main")

        # Verify the docstring exists
        assert promesh_mcp.__main__.__doc__ is not None
        assert "Entry point" in promesh_mcp.__main__.__doc__
