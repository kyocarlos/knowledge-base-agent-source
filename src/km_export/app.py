"""uvicorn entry point: ``uvicorn src.km_export.app:app --workers 1`` (the rate limit lives in the process)."""
from .service import create_app

app = create_app()
