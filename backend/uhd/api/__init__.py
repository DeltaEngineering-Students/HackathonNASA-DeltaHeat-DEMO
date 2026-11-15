"""FastAPI application: ``uvicorn uhd.api:app``."""

from uhd.api.app import create_app

app = create_app()

__all__ = ["app", "create_app"]
