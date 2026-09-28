"""HTTP routes for the service."""

from fastapi import APIRouter

from app.apis import chat, health, openai, ui

api_router = APIRouter()
api_router.include_router(ui.router)
api_router.include_router(health.router)
api_router.include_router(chat.router)
api_router.include_router(openai.router)
