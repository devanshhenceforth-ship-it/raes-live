from fastapi import APIRouter, UploadFile, File
import asyncio
import os
import base64
import socketio
import cv2
import tempfile
from typing import Optional
from langchain_core.messages import HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from .transcribe import transcribe_video_with_whisper

# ---------------------------------------------
# INIT
# ---------------------------------------------
load_dotenv()
router = APIRouter()

# ---------- Schemas ---------- #
class VideoEvent(BaseModel):
    timestamp: int
    task: str
    description: str
    category: str

class AllAnalyzerResponse(BaseModel):
    issues: list[VideoEvent] = Field(..., description="List of identified tasks or issues.")
    summary: Optional[str] = Field(None, description="Summary of the analysis.")

# ---------- Global LLM Setup ---------- #
llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", api_key=os.getenv("GOOGLE_API_KEY"))
structured_llm = llm.with_structured_output(AllAnalyzerResponse)

# ---------- Socket.IO Server ---------- #
sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")

@sio.event
async def connect(sid, environ):
    print("[SOCKET] Client connected:", sid)

@sio.event
async def disconnect(sid):
    print("[SOCKET] Client disconnected:", sid)

# ---------------------------------------------
# BASE64 UTILITY
# ---------------------------------------------
def frame_to_base64(frame) -> str:
    _, buffer = cv2.imencode(".jpg", frame)
    return base64.b64encode(buffer).decode()

def get_frame_at_timestamp(video_bytes: bytes, timestamp: int) -> Optional[str]:
    with tempfile.NamedTemporaryFile(suffix=".mp4") as tmp:
        tmp.write(video_bytes)
        tmp.flush()
        cap = cv2.VideoCapture(tmp.name)
        if not cap.isOpened():
            return None
        fps = cap.get(cv2.CAP_PROP_FPS) or 30
        frame_number = int((timestamp / 1000) * fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
        ret, frame = cap.read()
        cap.release()
        if ret:
            return frame_to_base64(frame)
    return None

# ---------------------------------------------
# BACKGROUND PROCESSING TASK
# ---------------------------------------------
async def process_video_background(video_bytes: bytes):
    try:
        video_b64 = base64.b64encode(video_bytes).decode()

        # Prepare LLM prompt
        prompt = (
            "Analyze the attached office video for maintenance, repairs, and cleaning issues "
            "(electrical, decor, furniture, etc.). "
            "For each issue, provide a structured list with: timestamp (ms), "
            "task name, description, and category. "
            "Write a summary for the whole video."
        )

        message = HumanMessage(
            content=[
                {"type": "text", "text": prompt},
                {"type": "media", "data": video_b64, "mime_type": "video/mp4"},
            ]
        )

        # Run LLM in thread
        result = await asyncio.to_thread(structured_llm.invoke, [message])

        # Extract screenshots
        screenshots = {issue.timestamp: get_frame_at_timestamp(video_bytes, issue.timestamp)
                       for issue in result.issues}

        # Emit results via Socket.IO
        response_payload = {
            "issues": [issue.dict() for issue in result.issues],
            "summary": result.summary,
            "screenshots": screenshots
        }
        await sio.emit("task_detected", response_payload)

    except Exception as e:
        print("[VIDEO_ANALYSIS] Error in background:", e)
        await sio.emit("task_error", {"error": str(e)})

# ---------------------------------------------
# VIDEO UPLOAD ENDPOINT (return transcription)
# ---------------------------------------------
@router.post("/upload_video")
async def upload_video(file: UploadFile = File(None)):
    if not file:
        return {"error": "No video provided"}

    video_bytes = await file.read()

    # 1️⃣ Transcribe video immediately
    transcript_segments = await transcribe_video_with_whisper(video_bytes)
    full_transcript = " ".join([seg["text"] for seg in transcript_segments])

    # 2️⃣ Start background processing for LLM + screenshots
    asyncio.create_task(process_video_background(video_bytes))

    # 3️⃣ Return transcription immediately
    return {
        "status": "ok",
        "message": "Video received. LLM analysis will be processed in background.",
        "transcript_segments": transcript_segments,
        "full_transcript": full_transcript
    }
