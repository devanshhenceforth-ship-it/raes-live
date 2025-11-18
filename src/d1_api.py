import subprocess
from fastapi import FastAPI, UploadFile, File, Body, APIRouter
from pathlib import Path
import asyncio
import cv2
import os
import base64
from dotenv import load_dotenv
from google.genai import Client
from langchain_core.messages import HumanMessage
from .schemas import AudioEvent, FrameSelection
from langchain_google_genai import ChatGoogleGenerativeAI
import socketio

# ---------------------------------------------
# INIT
# ---------------------------------------------
load_dotenv()

router = APIRouter()

CHUNK_FILE = Path("chunk.webm")
AUDIO_FILE = Path("audio.wav")
FRAMES_DIR = Path("frames")
FRAMES_DIR.mkdir(exist_ok=True)

audio_cache = []
frame_cache = []

analyzing = False

client = Client(api_key=os.getenv("GOOGLE_API_KEY"))

llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", api_key=os.getenv("GOOGLE_API_KEY"))
audio_llm = llm.with_structured_output(AudioEvent)
video_llm = llm.with_structured_output(FrameSelection)

sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")

# ---------------------------------------------
# BASE64 UTILITY
# ---------------------------------------------
def decode_base64(data: str) -> bytes:
    data = data.strip().replace("\n", "").replace(" ", "")
    missing_padding = len(data) % 4
    if missing_padding:
        data += "=" * (4 - missing_padding)
    return base64.b64decode(data)


# ---------------------------------------------
# PROCESS VIDEO CHUNK (AUDIO + FRAMES)
# ---------------------------------------------
async def process_chunk(raw: bytes):
    CHUNK_FILE.write_bytes(raw)

    # Extract audio
    subprocess.run([
        "ffmpeg", "-y", "-i", str(CHUNK_FILE),
        "-vn", "-acodec", "pcm_s16le",
        "-ar", "16000", "-ac", "1",
        str(AUDIO_FILE)
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    if AUDIO_FILE.exists():
        audio_cache.append(AUDIO_FILE.read_bytes())

    # Cleanup & extract frames
    for f in FRAMES_DIR.glob("*.jpg"):
        f.unlink()

    subprocess.run([
        "ffmpeg", "-y", "-i", str(CHUNK_FILE),
        "-vf", "fps=1", str(FRAMES_DIR / "frame-%03d.jpg")
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    frame_cache.clear()
    for f in sorted(FRAMES_DIR.glob("*.jpg")):
        img = cv2.imread(str(f))
        if img is not None:
            frame_cache.append(img)


# ---------------------------------------------
# ANALYZER LOOP
# ---------------------------------------------
async def analyzer_loop():
    global analyzing
    print("[ANALYZER] Started")

    while True:
        if analyzing or not audio_cache or not frame_cache:
            await asyncio.sleep(0.2)
            continue

        analyzing = True

        # ------------------ AUDIO ANALYSIS ------------------
        audio_bytes = b"".join(audio_cache)
        audio_cache.clear()

        try:
            msg = HumanMessage(
                content="Analyze audio for maintenance tasks.",
                media={"data": audio_bytes, "mime_type": "audio/wav"}
            )
            # Run synchronous invoke in thread to avoid blocking async loop
            audio_res = await asyncio.to_thread(audio_llm.invoke, [msg])
        except Exception as e:
            print("[AUDIO_ANALYZER] Error:", e)
            analyzing = False
            continue

        if not getattr(audio_res, "task_detected", False):
            analyzing = False
            continue

        # ------------------ FRAME SELECTION ------------------
        try:
            encoded_frames = []
            for frame in frame_cache:
                _, buf = cv2.imencode(".jpg", frame)
                encoded_frames.append(buf.tobytes())

            try:
                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=[
                        {"text": "Return JSON: { index: number } for best frame."},
                        *[
                            {"inline_data": {"data": img, "mime_type": "image/jpeg"}}
                            for img in encoded_frames
                        ]
                    ],
                    config={
                        "response_mime_type": "application/json",
                        "response_json_schema": FrameSelection.model_json_schema()
                    }
                )
                print("[VIDEO_ANALYZER] Gemini response received, response:", response.text)
            except Exception as e:
                print("[VIDEO_ANALYZER] Gemini frame error:", e)
                analyzing = False
                continue

            try:
                result = FrameSelection.model_validate_json(response.text)
                best = result.index
            except Exception as e:
                print("[VIDEO_ANALYZER] Bad frame index:", e)
                analyzing = False
                continue

        except Exception as e:
            print("[VIDEO_ANALYZER] Frame processing error:", e)
            analyzing = False
            continue

        # ------------------ EMIT EVENT ------------------
        frame = frame_cache[best]
        _, buf = cv2.imencode(".jpg", frame)
        img_b64 = base64.b64encode(buf).decode()

        await sio.emit("task_detected", {
            "image_base64": img_b64,
            "meta": audio_res.dict() if hasattr(audio_res, "dict") else {}
        })

        analyzing = False
        await asyncio.sleep(0.2)


# ---------------------------------------------
# SOCKET EVENTS
# ---------------------------------------------
@sio.event
async def connect(sid, environ):
    print("[SOCKET] Client connected:", sid)
    asyncio.create_task(analyzer_loop())


@sio.event
async def disconnect(sid):
    print("[SOCKET] Client disconnected:", sid)


@router.post("/upload_chunk")
async def upload_chunk(
    file: UploadFile = File(None),
    chunk_base64: str = Body(None)
):
    if file:
        raw = await file.read()
    elif chunk_base64:
        raw = decode_base64(chunk_base64)
    else:
        return {"error": "missing chunk"}

    # process → extract frames + audio
    await process_chunk(raw)

    return {"status": "ok", "received": len(raw)}
