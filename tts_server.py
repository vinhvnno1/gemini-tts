"""
Text-to-Speech Server với Gemini 2.0 Flash Native Audio
Có hệ thống đăng nhập Admin
"""

import asyncio
import json
import os
import base64
import secrets
import hashlib
from pathlib import Path
from datetime import datetime, timedelta

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request, Response, Depends, Cookie
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel
from google import genai
from google.genai import types

load_dotenv()

# Configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY environment variable is required")

# Admin credentials (có thể đổi qua env)
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")

MODEL = "gemini-2.5-flash-native-audio-preview-12-2025"
CONFIG = {
    "response_modalities": ["AUDIO"],
    "system_instruction": """You are a text-to-speech assistant.
When given text, read it aloud naturally and expressively.
Match the language of the input text.
Do not add any commentary, just read the text as given.""",
}

# Initialize
client = genai.Client(api_key=GEMINI_API_KEY)
app = FastAPI(title="Text-to-Speech with Gemini")

# Get current directory
BASE_DIR = Path(__file__).parent

# Session storage (in-memory, reset khi restart)
sessions = {}


class LoginRequest(BaseModel):
    username: str
    password: str


def create_session(username: str) -> str:
    """Tạo session token mới"""
    token = secrets.token_hex(32)
    sessions[token] = {
        "username": username,
        "created_at": datetime.now(),
        "expires_at": datetime.now() + timedelta(hours=24)
    }
    return token


def verify_session(token: str) -> bool:
    """Kiểm tra session token còn hợp lệ không"""
    if not token or token not in sessions:
        return False
    session = sessions[token]
    if datetime.now() > session["expires_at"]:
        del sessions[token]
        return False
    return True


async def get_current_user(session_token: str = Cookie(None)):
    """Dependency để kiểm tra đăng nhập"""
    if not verify_session(session_token):
        return None
    return sessions[session_token]["username"]


# Health check
@app.get("/api/health")
async def health_check():
    return {"status": "ok", "model": MODEL}


# Login API
@app.post("/api/login")
async def login(request: LoginRequest, response: Response):
    if request.username == ADMIN_USERNAME and request.password == ADMIN_PASSWORD:
        token = create_session(request.username)
        response.set_cookie(
            key="session_token",
            value=token,
            httponly=True,
            max_age=86400,  # 24 hours
            samesite="lax"
        )
        return {"success": True, "message": "Đăng nhập thành công"}
    return JSONResponse(
        status_code=401,
        content={"success": False, "message": "Sai tên đăng nhập hoặc mật khẩu"}
    )


# Logout API
@app.post("/api/logout")
async def logout(response: Response, session_token: str = Cookie(None)):
    if session_token and session_token in sessions:
        del sessions[session_token]
    response.delete_cookie("session_token")
    return {"success": True, "message": "Đã đăng xuất"}


# Check auth API
@app.get("/api/me")
async def get_me(session_token: str = Cookie(None)):
    if verify_session(session_token):
        return {"logged_in": True, "username": sessions[session_token]["username"]}
    return {"logged_in": False}


# Serve login page
@app.get("/")
async def serve_index(session_token: str = Cookie(None)):
    if verify_session(session_token):
        return RedirectResponse(url="/tts")
    return FileResponse(BASE_DIR / "login.html")


@app.get("/login")
async def serve_login():
    return FileResponse(BASE_DIR / "login.html")


# Serve TTS page (protected)
@app.get("/tts")
async def serve_tts(session_token: str = Cookie(None)):
    if not verify_session(session_token):
        return RedirectResponse(url="/")
    return FileResponse(BASE_DIR / "tts.html")


# WebSocket TTS handler - real-time streaming
@app.websocket("/ws/tts")
async def websocket_tts(websocket: WebSocket):
    await websocket.accept()
    print("TTS client connected")

    try:
        while True:
            # Receive text from client
            data = await websocket.receive_text()
            message = json.loads(data)

            if message.get("type") == "tts":
                text = message.get("text", "")
                if not text:
                    continue

                print(f"TTS request: {text[:50]}...")

                try:
                    # Connect to Gemini for this TTS request
                    async with client.aio.live.connect(
                        model=MODEL,
                        config=CONFIG
                    ) as session:
                        # Send text to be spoken
                        await session.send_client_content(
                            turns=[{"role": "user", "parts": [{"text": f"Please read this text aloud: {text}"}]}],
                            turn_complete=True
                        )

                        # Receive and forward audio chunks
                        turn = session.receive()
                        async for response in turn:
                            if response.server_content and response.server_content.model_turn:
                                for part in response.server_content.model_turn.parts:
                                    if part.inline_data and part.inline_data.data:
                                        audio_b64 = base64.b64encode(part.inline_data.data).decode('utf-8')
                                        await websocket.send_json({
                                            "type": "audio",
                                            "data": audio_b64
                                        })

                            if response.server_content and response.server_content.turn_complete:
                                await websocket.send_json({"type": "complete"})
                                break

                except Exception as e:
                    print(f"TTS error: {e}")
                    await websocket.send_json({"type": "error", "message": str(e)})

    except WebSocketDisconnect:
        print("TTS client disconnected")
    except Exception as e:
        print(f"WebSocket error: {e}")


# Serve static files
@app.get("/{filename}")
async def serve_file(filename: str, session_token: str = Cookie(None)):
    # Allow static assets without auth
    if filename.endswith(('.css', '.js', '.png', '.ico', '.svg')):
        file_path = BASE_DIR / filename
        if file_path.exists() and file_path.is_file():
            return FileResponse(file_path)
    
    # Protect HTML files
    if not verify_session(session_token):
        return RedirectResponse(url="/")
    
    file_path = BASE_DIR / filename
    if file_path.exists() and file_path.is_file():
        return FileResponse(file_path)
    return RedirectResponse(url="/tts")


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 3000))
    print("🎤 Starting Text-to-Speech Server with Admin Auth...")
    print(f"📡 Open http://localhost:{port} in your browser")
    print(f"👤 Default login: {ADMIN_USERNAME} / {ADMIN_PASSWORD}")
    uvicorn.run(app, host="0.0.0.0", port=port)

