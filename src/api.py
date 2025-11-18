import subprocess
from fastapi import APIRouter, WebSocket
from pathlib import Path
from collections import deque
import asyncio
import cv2
from google.genai import Client
import os
import base64
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from .schemas import AudioEvent, FrameSelection
from langchain_google_genai import ChatGoogleGenerativeAI

load_dotenv()
router = APIRouter()

# ----------------- WS MANAGER -----------------
class WSManager:
    def __init__(self):
        self.active = set()

    async def connect(self, ws: WebSocket):
        self.active.add(ws)
        print(f"[WS] Connected clients: {len(self.active)}")

    def disconnect(self, ws: WebSocket):
        if ws in self.active:
            self.active.remove(ws)
            print(f"[WS] Client disconnected. Remaining: {len(self.active)}")

    async def broadcast(self, data: dict):
        print(f"[WS] Broadcasting → {len(self.active)} clients")
        dead = []
        for ws in self.active:
            try:
                await ws.send_json(data)
            except:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

ws_manager = WSManager()

# ----------------- BUFFERS -----------------
CHUNK_FILE = Path("chunk.webm")
AUDIO_FILE = Path("audio.wav")
FRAME_DIR = Path("frames/")
FRAME_DIR.mkdir(exist_ok=True)

video_cache = deque(maxlen=10)
audio_cache = deque(maxlen=5)

client = Client(api_key=os.getenv("GOOGLE_API_KEY"))

# analyzer lock
analyzing_audio = False

# Setup Gemini
llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    api_key=os.getenv("GOOGLE_API_KEY"),
)
audio_llm = llm.with_structured_output(AudioEvent)

# ----------------- AUDIO ANALYSIS -----------------
async def analyze_audio(audio_bytes: bytes):
    print(f"[AUDIO] Analyzing audio bytes = {len(audio_bytes)}")
    if not audio_bytes:
        return False, None

    prompt = """
    "Analyze the attached audio for maintenance, repairs, and cleaning issues (electrical, decor, furniture, etc.). "
    Transcribe the audio. If it contains a task, return:
    - task_detected = true
    - list of VideoEvent items
    Otherwise return task_detected = false.
    """
    try:
        message = HumanMessage(
            content=[
                {"type": "text", "text": prompt},
                {"type": "media", "data": audio_bytes, "mime_type": "audio/wav"},
            ]
        )
        data = audio_llm.invoke([message])
    except Exception as e:
        print("[AUDIO] ERROR calling Gemini:", e)
        return False, None

    print("[AUDIO] Parsed response:", data)
    return data.task_detected, data

# ----------------- VIDEO PROCESSING -----------------
async def process_video_chunk(video_buffer: bytearray):
    if not video_buffer:
        return

    CHUNK_FILE.write_bytes(video_buffer)
    video_buffer.clear()

    # extract audio
    subprocess.run([
        "ffmpeg", "-y", "-i", str(CHUNK_FILE),
        "-vn", "-acodec", "pcm_s16le",
        "-ar", "16000", "-ac", "1", str(AUDIO_FILE)
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    audio_bytes = AUDIO_FILE.read_bytes()
    audio_cache.append(audio_bytes)

    # clean frames
    for f in FRAME_DIR.glob("frame-*.jpg"):
        f.unlink()

    # extract frames
    subprocess.run([
        "ffmpeg", "-y", "-i", str(CHUNK_FILE),
        "-vf", "fps=1", str(FRAME_DIR / "frame-%03d.jpg")
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    frame_files = sorted(FRAME_DIR.glob("frame-*.jpg"))
    for frame_file in frame_files:
        frame = cv2.imread(str(frame_file))
        if frame is not None:
            video_cache.append((frame, 0))

# ----------------- VIDEO ANALYSIS -----------------
async def analyze_video():
    global analyzing_audio
    print("[VIDEO_ANALYZER] Started")

    while True:
        if analyzing_audio:
            await asyncio.sleep(0.2)
            continue

        if not audio_cache or not video_cache:
            await asyncio.sleep(0.3)
            continue

        analyzing_audio = True
        frames_to_check = list(video_cache)
        audio_bytes = b"".join(audio_cache)

        task_triggered, data = await analyze_audio(audio_bytes)

        if task_triggered:
            images = []
            for frame, _ in frames_to_check:
                _, b = cv2.imencode(".jpg", frame)
                images.append(b.tobytes())

            try:
                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=[
                        {"text": "Return JSON: { index: number } for best frame."},
                        *[
                            {"inline_data": {"data": img, "mime_type": "image/jpeg"}}
                            for img in images
                        ]
                    ],
                    config={
                        "response_mime_type": "application/json",
                        "response_json_schema": FrameSelection.model_json_schema()
                    }
                )
            except Exception as e:
                print("[VIDEO_ANALYZER] Gemini frame error:", e)
                analyzing_audio = False
                continue

            try:
                result = FrameSelection.model_validate_json(response.text)
                idx = result.index
            except:
                print("[VIDEO_ANALYZER] Bad frame index:", response.text)
                analyzing_audio = False
                continue

            chosen_frame, _ = frames_to_check[idx]
            _, buf = cv2.imencode(".jpg", chosen_frame)
            img_b64 = base64.b64encode(buf).decode()

            await ws_manager.broadcast({
                "event": "task_detected",
                "image_base64": img_b64,
                "meta": data.model_dump()
            })

        analyzing_audio = False
        await asyncio.sleep(0.2)

# ----------------- WEBSOCKET ENDPOINT -----------------
@router.websocket("/stream")
async def stream_video(websocket: WebSocket):
    await websocket.accept()
    await ws_manager.connect(websocket)

    video_buffer = bytearray()  # per-client buffer

    # start analyzer once
    if not hasattr(router, "analyzer_started"):
        router.analyzer_started = True
        asyncio.create_task(analyze_video())

    # background task for processing chunks
    async def chunk_processor():
        while True:
            try:
                if video_buffer:
                    await process_video_chunk(video_buffer)
            except Exception as e:
                print("[CHUNK_PROCESSOR] Error:", e)
            await asyncio.sleep(0.05)

    processor_task = asyncio.create_task(chunk_processor())

    try:
        while True:
            try:
                chunk = await websocket.receive_bytes()
                video_buffer.extend(chunk)
            except Exception as e:
                print("[WS] Receive error:", e)
                break

    finally:
        processor_task.cancel()
        ws_manager.disconnect(websocket)
