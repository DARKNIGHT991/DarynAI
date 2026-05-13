"""Compatibility entrypoint for running Daryn AI with `uvicorn server:app`."""

from app.main import app

__all__ = ["app"]
