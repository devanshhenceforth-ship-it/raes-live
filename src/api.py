from fastapi import APIRouter, UploadFile, File, BackgroundTasks, HTTPException
import base64
import asyncio
from langchain_core.messages import HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, Field
from typing import List, Optional
import os
import socketio
import cv2
import tempfile
from dotenv import load_dotenv
import httpx

# from .transcribe import transcribe_video_bytes as transcribe_video_with_deepgram

# ---------------------------------------------
# INIT
# ---------------------------------------------
load_dotenv()
router = APIRouter()

DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")


# ---------- Schemas ---------- #
class VideoEvent(BaseModel):
    timestamp: int
    task: str
    description: str
    category: str


class AllAnalyzerResponse(BaseModel):
    issues: List[VideoEvent] = Field(
        ..., description="List of identified tasks or issues."
    )
    summary: Optional[str] = Field(None, description="Summary of the analysis.")


# ---------- Global LLM Setup ---------- #
llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash", api_key=os.getenv("GOOGLE_API_KEY")
)
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
def decode_base64(data: str) -> bytes:
    data = data.strip().replace("\n", "").replace(" ", "")
    missing_padding = len(data) % 4
    if missing_padding:
        data += "=" * (4 - missing_padding)
    return base64.b64decode(data)


def frame_to_base64(frame) -> str:
    """Convert an OpenCV frame to base64 JPEG"""
    _, buffer = cv2.imencode(".jpg", frame)
    return base64.b64encode(buffer).decode()


def get_frame_at_timestamp(video_bytes: bytes, timestamp: int) -> Optional[str]:
    """Extract a frame at the given timestamp (ms) from video bytes"""
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
# BACKGROUND ANALYSIS FUNCTION (PARALLEL)
# ---------------------------------------------
async def analyze_video_background(video_bytes: bytes):
    try:
        # --- Define async tasks ---
        async def transcribe_task():
            # return await transcribe_video_with_deepgram(video_bytes) or ""
            return "this is demo transcription"

        async def llm_task():
            video_b64 = base64.b64encode(video_bytes).decode()
            prompt = (
                "Analyze the attached office video for maintenance, repairs, and cleaning issues "
                "(electrical, decor, furniture, etc.). "
                "For each issue, provide a structured list with: timestamp (ms), "
                "task name, description, and category. "
                "Write a summary for the whole video as well."
            )
            message = HumanMessage(
                content=[
                    {"type": "text", "text": prompt},
                    {"type": "media", "data": video_b64, "mime_type": "video/mp4"},
                ]
            )
            return await asyncio.to_thread(structured_llm.invoke, [message])

        # --- Run both tasks concurrently ---
        transcription, llm_result = await asyncio.gather(transcribe_task(), llm_task())

        # --- Add screenshots for frontend ---
        issues_with_screenshots = []
        for issue in llm_result.issues:
            screenshot_b64 = get_frame_at_timestamp(video_bytes, issue.timestamp)
            issue_dict = issue.dict()
            issue_dict["screenshot_b64"] = screenshot_b64 or ""
            issues_with_screenshots.append(issue_dict)

        # --- Emit Socket.IO event ---
        response_payload = {
            "issues": issues_with_screenshots,
            "summary": llm_result.summary,
            # "transcription": transcription,
        }

        await sio.emit("task_detected", response_payload)

    except Exception as e:
        print("[VIDEO_ANALYSIS] Background Error:", e)
        await sio.emit("task_error", {"error": str(e)})


def extract_transcript(deepgram_response: dict) -> str:
    """
    Extracts the main transcript text from a Deepgram transcription response.
    """
    try:
        # Navigate to the first channel, first alternative
        return deepgram_response["results"]["channels"][0]["alternatives"][0][
            "transcript"
        ]
    except (KeyError, IndexError):
        return ""


async def transcribe_video(video_bytes: bytes, content_type: str):
    """
    Send video/audio bytes to Deepgram and return transcription JSON.
    """
    url = "https://api.deepgram.com/v1/listen?model=nova-3&smart_format=true"

    headers = {
        "Authorization": f"Token {DEEPGRAM_API_KEY}",
        "Content-Type": content_type,  # 'video/mp4' or 'audio/wav' etc.
    }

    timeout = httpx.Timeout(connect=10.0, read=120.0, write=300.0, pool=120.0)

    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            response = await client.post(url, headers=headers, content=video_bytes)
            response.raise_for_status()
            return extract_transcript(response.json())
        except httpx.HTTPStatusError as e:
            # Log the Deepgram response body for debugging
            print("Deepgram returned error:", e.response.text)
            raise HTTPException(
                status_code=e.response.status_code, detail=e.response.text
            )


# ---------------------------------------------
# VIDEO UPLOAD ENDPOINT
# ---------------------------------------------
@router.post("/upload_video")
async def upload_video(
    file: UploadFile = File(None),
    background_tasks: BackgroundTasks = None,
    # sid: Optional[str] = None
):
    if not file:
        return {"error": "No video provided"}

    content_type = file.content_type or "video/mp4"
    video_bytes = await file.read()

    # Start background task if sid is provided
    # if sid:
    background_tasks.add_task(analyze_video_background, video_bytes)
    transcription = await transcribe_video(video_bytes, content_type)

    return {
        "status": "ok",
        "message": "Video received. Analysis is running in background.",
        "transcription": transcription,
    }
