"""Dedicated KM Control Auth service; it does not mount KM business APIs."""
from fastapi import FastAPI
from src.control_auth_routes import oidc_router, router

app = FastAPI(title="KM Control Auth", version="1.0.0")
app.include_router(router)
app.include_router(oidc_router)

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "km-control-auth"}
