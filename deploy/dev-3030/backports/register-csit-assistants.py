"""Register the CSIT assistant routes in the deployed web image.

The deployed src/web_api/__init__.py is older than git's (no CSIT read-only router), so the file is not replaced: exactly one
anchor line gets two lines after it, and the build fails if the anchor is missing or the routes are already registered.
"""
from pathlib import Path

target = Path("/app/src/web_api/__init__.py")
text = target.read_text(encoding="utf-8")
anchor = "app.include_router(wifi8_router)\n"
if text.count(anchor) != 1 or "csit_assistant_router" in text:
    raise SystemExit("anchor missing or assistants already registered; refusing to patch")
text = text.replace(anchor, anchor + "from .csit_assistant_routes import router as csit_assistant_router\napp.include_router(csit_assistant_router)\n")
compile(text, str(target), "exec")  # a syntax error fails the build, not the container start
target.write_text(text, encoding="utf-8")
