import subprocess
from fastapi import APIRouter, WebSocket
from pathlib import Path
from collections import deque
import asyncio
import cv2
from google.genai import Client
import os
from dotenv import load_dotenv

load_dotenv()
router = APIRouter()

# Buffer to store incoming video chunks
video_buffer = bytearray()

CHUNK_FILE = Path("chunk.webm")      # temporary video chunk file
AUDIO_FILE = Path("audio.wav")       # extracted audio
FRAME_DIR = Path("frames/")          # extracted frames folder
FRAME_DIR.mkdir(exist_ok=True)

# Minimal caches for analysis
video_cache = deque(maxlen=10)
audio_cache = deque(maxlen=5)

# Gemini client
client = Client(api_key=os.getenv("GOOGLE_API_KEY"))


# ----------------- AUDIO ANALYSIS -----------------
async def analyze_audio(audio_bytes: bytes):
    if not audio_bytes:
        return False
    print(f"[LOG] Sending audio of length {len(audio_bytes)} to Gemini for analysis...")
    prompt = "Transcribe the event happens in this audio chunk."
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[
            {"text": prompt},
            {"inline_data": {"data": audio_bytes, "mime_type": "audio/wav"}}
        ]
    )
    detected = "task detected" in response.text.lower()
    print(f"[LOG] Audio analysis result: {'TASK DETECTED' if detected else 'No task'}", response.text)
    return detected


# ----------------- VIDEO PROCESSING -----------------
async def process_video_chunk():
    """
    Writes current buffer to a WebM file and extracts:
    - audio.wav (16kHz mono)
    - frames/frame-%03d.jpg (1 FPS)
    Also updates caches for analysis.
    """
    global video_buffer

    if not video_buffer:
        return

    # Write the buffer to a temporary .webm file
    CHUNK_FILE.write_bytes(video_buffer)
    video_buffer.clear()  # clear buffer after writing

    # ---- Extract audio ----
    subprocess.run([
        "ffmpeg", "-y",
        "-i", str(CHUNK_FILE),
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        str(AUDIO_FILE)
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Cache audio bytes
    audio_bytes = AUDIO_FILE.read_bytes()
    audio_cache.append(audio_bytes)

    # ---- Extract frames at 1 FPS ----
    subprocess.run([
        "ffmpeg", "-y",
        "-i", str(CHUNK_FILE),
        "-vf", "fps=1",
        str(FRAME_DIR / "frame-%03d.jpg")
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Cache frames
    for frame_file in sorted(FRAME_DIR.glob("frame-*.jpg")):
        frame = cv2.imread(str(frame_file))
        video_cache.append((frame, 0))  # timestamp 0 for simplicity

    print("Processed video chunk → audio + frames cached")


# ----------------- VIDEO ANALYSIS -----------------
async def analyze_video():
    while True:
        if not video_cache:
            await asyncio.sleep(0.5)
            continue

        frames_to_check = list(video_cache)
        frames_only = [f for f, _ in frames_to_check if f is not None]

        # Merge all audio chunks from audio_cache
        audio_bytes = b"".join(list(audio_cache))
        audio_cache.clear()

        task_triggered = await analyze_audio(audio_bytes)

        if task_triggered:
            print(f"[LOG] Task triggered, sending {len(frames_to_check)} frames to Gemini for visual analysis...")
            images_for_ai = []
            for frame, ts in frames_to_check:
                if frame is None:
                    continue
                _, buffer = cv2.imencode(".jpg", frame)
                images_for_ai.append(buffer.tobytes())

            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[
                    {"text": "Pick the most relevant frame for this task from these images."},
                    *[{"inline_data": {"data": img, "mime_type": "image/jpeg"}} for img in images_for_ai]
                ]
            )
            try:
                chosen_frame_index = int(response.text.strip())
                chosen_frame, chosen_ts = frames_to_check[chosen_frame_index]
                print(f"[LOG] Chosen frame index: {chosen_frame_index}, timestamp: {chosen_ts:.2f}s")
            except Exception as e:
                print(f"[LOG] Error parsing AI response: {response.text}, Error: {e}")

        await asyncio.sleep(0.5)


# ----------------- WEBSOCKET -----------------
@router.websocket("/stream")
async def stream_video(websocket: WebSocket):
    """
    Receives binary video chunks from Android via WebSocket.
    """
    await websocket.accept()
    print("[WS] Client connected")

    global video_buffer

    # Start background video analysis task
    asyncio.create_task(analyze_video())

    while True:
        try:
            chunk = await websocket.receive_bytes()
            print(f"[WS] Received chunk {len(chunk)} bytes")

            # Append to buffer
            video_buffer.extend(chunk)

            # Process the updated buffer
            await process_video_chunk()

        except Exception as e:
            print("[WS] Error:", e)
            break
