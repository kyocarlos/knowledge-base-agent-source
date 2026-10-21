"""Dedicated data-plane bridge process with the deployed KM source tree."""
from fastapi import FastAPI
from src.web_api.cross_search_bridge import router

app = FastAPI(title="KM internal search bridge")
app.include_router(router)
