"""
Text-to-Speech Server với Gemini 2.0 Flash Native Audio
Nhập text -> Gemini chuyển thành giọng nói real-time
Hỗ trợ đọc văn bản dài bằng cách chia nhỏ
"""

import asyncio
import json
import os
import re
import base64
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from google import genai

load_dotenv()

# Configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY environment variable is required")

MODEL = "gemini-2.5-flash-native-audio-preview-12-2025"
CONFIG = {
    "response_modalities": ["AUDIO"],
    "system_instruction": """You are a text-to-speech assistant.
When given text, read it aloud naturally and expressively.
Match the language of the input text.
Do not add any commentary, just read the text as given.
Read the COMPLETE text, do not stop early or summarize.""",
}

# Max characters per chunk (để đảm bảo đọc hết)
MAX_CHUNK_SIZE = 500

# Initialize
client = genai.Client(api_key=GEMINI_API_KEY)
app = FastAPI(title="Text-to-Speech with Gemini")

# Get current directory
BASE_DIR = Path(__file__).parent


def split_text_into_chunks(text: str, max_size: int = MAX_CHUNK_SIZE) -> list:
    """Chia text thành các đoạn nhỏ theo câu, không vượt quá max_size"""
    if len(text) <= max_size:
        return [text]
    
    # Split by sentences (Vietnamese and English)
    sentences = re.split(r'(?<=[.!?。！？])\s*', text)
    
    chunks = []
    current_chunk = ""
    
    for sentence in sentences:
        if not sentence.strip():
            continue
            
        # Nếu 1 câu quá dài, chia theo dấu phẩy hoặc theo độ dài
        if len(sentence) > max_size:
            if current_chunk:
                chunks.append(current_chunk.strip())
                current_chunk = ""
            
            # Chia theo dấu phẩy
            sub_parts = re.split(r'(?<=[,，;；])\s*', sentence)
            for part in sub_parts:
                if len(current_chunk) + len(part) <= max_size:
                    current_chunk += part
                else:
                    if current_chunk:
                        chunks.append(current_chunk.strip())
                    current_chunk = part
        elif len(current_chunk) + len(sentence) <= max_size:
            current_chunk += sentence + " "
        else:
            if current_chunk:
                chunks.append(current_chunk.strip())
            current_chunk = sentence + " "
    
    if current_chunk.strip():
        chunks.append(current_chunk.strip())
    
    return chunks if chunks else [text]


# Health check
@app.get("/api/health")
async def health_check():
    return {"status": "ok", "model": MODEL}


# WebSocket TTS handler - real-time streaming
@app.websocket("/ws/tts")
async def websocket_tts(websocket: WebSocket):
    await websocket.accept()
    print("TTS client connected")

    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)

            if message.get("type") == "tts":
                text = message.get("text", "")
                if not text:
                    continue

                # Chia text thành các đoạn nhỏ
                chunks = split_text_into_chunks(text)
                total_chunks = len(chunks)
                print(f"TTS request: {len(text)} chars, {total_chunks} chunks")

                try:
                    for chunk_idx, chunk in enumerate(chunks):
                        print(f"Processing chunk {chunk_idx + 1}/{total_chunks}: {chunk[:50]}...")
                        
                        # Thông báo tiến trình
                        await websocket.send_json({
                            "type": "progress",
                            "current": chunk_idx + 1,
                            "total": total_chunks
                        })
                        
                        async with client.aio.live.connect(
                            model=MODEL,
                            config=CONFIG
                        ) as session:
                            await session.send_client_content(
                                turns=[{"role": "user", "parts": [{"text": f"Read this text aloud completely: {chunk}"}]}],
                                turn_complete=True
                            )

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
                                    break
                    
                    # Tất cả chunks đã xong
                    await websocket.send_json({"type": "complete"})

                except Exception as e:
                    print(f"TTS error: {e}")
                    await websocket.send_json({"type": "error", "message": str(e)})

    except WebSocketDisconnect:
        print("TTS client disconnected")
    except Exception as e:
        print(f"WebSocket error: {e}")


# Serve TTS page
@app.get("/")
async def serve_index():
    return FileResponse(BASE_DIR / "tts.html")


@app.get("/{filename}")
async def serve_file(filename: str):
    file_path = BASE_DIR / filename
    if file_path.exists() and file_path.is_file():
        return FileResponse(file_path)
    return FileResponse(BASE_DIR / "tts.html")


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 3000))
    print("🎤 Starting Text-to-Speech Server...")
    print(f"📡 Open http://localhost:{port} in your browser")
    uvicorn.run(app, host="0.0.0.0", port=port)
