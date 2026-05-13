from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .db import init_db
from .routers import admin, auth, chat, chats, plans, profile, static, voice

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

init_db()

app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(chats.router)
app.include_router(static.router)
app.include_router(auth.router)
app.include_router(profile.router)
app.include_router(plans.router)
app.include_router(admin.router)
app.include_router(voice.router)
app.include_router(chat.router)
