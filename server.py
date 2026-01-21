"""
Voice AI Server - Real-time audio streaming with Gemini 2.0 Flash
Python/FastAPI version
"""

import asyncio
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from google import genai
from google.genai import types

load_dotenv()

# Configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY environment variable is required")

MODEL = "gemini-2.5-flash-native-audio-preview-12-2025"
CONFIG = {
    "response_modalities": ["AUDIO"],
    "system_instruction": """You are a helpful and friendly AI voice assistant. 
Keep your responses concise and natural-sounding. 
Respond in the same language the user speaks to you.
Be warm, engaging, and conversational.""",
}

# Initialize
client = genai.Client(api_key=GEMINI_API_KEY)
app = FastAPI(title="Voice AI with Gemini")

# Get current directory
BASE_DIR = Path(__file__).parent


# Health check
@app.get("/api/health")
async def health_check():
    return {"status": "ok", "model": MODEL}


# WebSocket handler
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    print("Client connected")

    gemini_session = None
    is_connected = True
    audio_queue = asyncio.Queue()

    async def send_to_client(message: dict):
        """Send message to client if connected"""
        if is_connected:
            try:
                await websocket.send_json(message)
            except Exception as e:
                print(f"Error sending to client: {e}")

    async def receive_from_gemini():
        """Receive audio from Gemini and forward to client"""
        nonlocal is_connected
        try:
            while is_connected and gemini_session:
                turn = gemini_session.receive()
                async for response in turn:
                    if not is_connected:
                        break

                    # Handle model response
                    if response.server_content and response.server_content.model_turn:
                        for part in response.server_content.model_turn.parts:
                            if part.inline_data and part.inline_data.data:
                                # Send audio chunk (already base64 encoded)
                                import base64
                                audio_b64 = base64.b64encode(part.inline_data.data).decode('utf-8')
                                await send_to_client({
                                    "type": "audio",
                                    "data": audio_b64
                                })
                            if part.text:
                                await send_to_client({
                                    "type": "text",
                                    "data": part.text
                                })

                    # Handle turn complete
                    if response.server_content and response.server_content.turn_complete:
                        await send_to_client({"type": "turnComplete"})

                    # Handle interruption
                    if response.server_content and response.server_content.interrupted:
                        await send_to_client({"type": "interrupted"})

        except Exception as e:
            print(f"Error receiving from Gemini: {e}")
            if is_connected:
                await send_to_client({"type": "error", "message": str(e)})

    async def send_to_gemini():
        """Send audio from queue to Gemini"""
        nonlocal is_connected
        try:
            while is_connected and gemini_session:
                audio_data = await audio_queue.get()
                if audio_data is None:
                    break
                await gemini_session.send_realtime_input(
                    audio={"data": audio_data, "mime_type": "audio/pcm"}
                )
        except Exception as e:
            print(f"Error sending to Gemini: {e}")

    try:
        # Connect to Gemini
        gemini_session = await client.aio.live.connect(
            model=MODEL,
            config=CONFIG
        )
        print("Connected to Gemini Live API")
        await send_to_client({"type": "connected"})

        # Start receive task
        receive_task = asyncio.create_task(receive_from_gemini())
        send_task = asyncio.create_task(send_to_gemini())

        # Handle messages from client
        while is_connected:
            try:
                data = await websocket.receive_text()
                message = json.loads(data)

                if message.get("type") == "audio":
                    # Decode base64 audio and queue for sending
                    import base64
                    audio_bytes = base64.b64decode(message["data"])
                    await audio_queue.put(audio_bytes)

            except WebSocketDisconnect:
                print("Client disconnected")
                break
            except Exception as e:
                print(f"Error processing message: {e}")
                break

    except Exception as e:
        print(f"Error: {e}")
        await send_to_client({"type": "error", "message": str(e)})

    finally:
        is_connected = False
        await audio_queue.put(None)  # Signal to stop send task

        if gemini_session:
            gemini_session.close()

        print("Connection closed")


# Serve static files
app.mount("/static", StaticFiles(directory=BASE_DIR), name="static")


# Serve index.html
@app.get("/")
async def serve_index():
    return FileResponse(BASE_DIR / "index.html")


@app.get("/{filename}")
async def serve_file(filename: str):
    file_path = BASE_DIR / filename
    if file_path.exists() and file_path.is_file():
        return FileResponse(file_path)
    return FileResponse(BASE_DIR / "index.html")


if __name__ == "__main__":
    import uvicorn
    print("🚀 Starting Voice AI Server...")
    print(f"📡 Open http://localhost:3000 in your browser")
    uvicorn.run(app, host="0.0.0.0", port=3000)
