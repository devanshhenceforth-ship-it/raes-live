# # video_upload_api.py
# from fastapi import APIRouter, UploadFile, File
# from video_logic import extract_video_screenshots

# import base64
# import cv2
# import tempfile
# import subprocess
# import os
# import httpx
# import logging

# router = APIRouter()
# DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")  # set your key in env

# # Setup logging
# logging.basicConfig(level=logging.INFO)
# logger = logging.getLogger("video_upload_api")


# def frame_to_b64(frame):
#     _, buffer = cv2.imencode(".jpg", frame)
#     return base64.b64encode(buffer).decode("utf-8")


# async def transcribe_audio(video_path: str) -> dict:
#     """
#     Extract audio from video and send to Deepgram for transcription.
#     Returns dict with 'transcript' and 'words' (id, word, start, end).
#     """
#     logger.info(f"Starting audio transcription for: {video_path}")

#     temp_audio_path = None
#     audio_bytes = None
#     try:
#         with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_audio:
#             temp_audio_path = temp_audio.name

#         logger.info("Extracting audio from video using ffmpeg...")
#         result = subprocess.run(
#             [
#                 "ffmpeg",
#                 "-y",
#                 "-i",
#                 video_path,
#                 "-vn",
#                 "-acodec",
#                 "pcm_s16le",
#                 "-ar",
#                 "16000",
#                 "-ac",
#                 "1",
#                 temp_audio_path,
#             ],
#             check=True,
#             capture_output=True,
#             text=True,
#             timeout=30,
#         )

#         if os.path.getsize(temp_audio_path) == 0:
#             logger.warning("Extracted audio file is empty.")
#             return {"transcript": "", "words": []}

#         with open(temp_audio_path, "rb") as f:
#             audio_bytes = f.read()

#     finally:
#         if temp_audio_path and os.path.exists(temp_audio_path):
#             os.remove(temp_audio_path)

#     if not audio_bytes:
#         return {"transcript": "", "words": []}

#     url = "https://api.deepgram.com/v1/listen"
#     params = {"model": "nova-3", "smart_format": "true", "punctuate": "true"}
#     headers = {
#         "Authorization": f"Token {DEEPGRAM_API_KEY}",
#         "Content-Type": "audio/wav",
#     }

#     async with httpx.AsyncClient(timeout=60.0) as client:
#         resp = await client.post(
#             url, params=params, headers=headers, content=audio_bytes
#         )
#         resp.raise_for_status()
#         data = resp.json()
#         alt = data["results"]["channels"][0]["alternatives"][0]

#         words = [
#             {"id": idx + 1, "word": w["word"], "start": w["start"], "end": w["end"]}
#             for idx, w in enumerate(alt.get("words", []))
#         ]
#         transcript = alt.get("transcript", "")
#         return {"transcript": transcript, "words": words}


# @router.post("/upload-video")
# async def upload_video(file: UploadFile = File(...)):
#     """
#     Accept whole video file upload, extract screenshots and audio transcript,
#     return as base64.
#     """
#     logger.info(f"Received video upload: {file.filename} ({file.content_type})")
#     content = await file.read()

#     with tempfile.NamedTemporaryFile(suffix=".mp4", delete=True) as temp_video:
#         temp_video.write(content)
#         temp_video.flush()
#         logger.info(f"Saved temporary video file: {temp_video.name}")

#         # Extract screenshots directly from temp file
#         logger.info("Extracting screenshots from video...")
#         screenshots = extract_video_screenshots(temp_video.name, every_n_frames=60)
#         logger.info(f"Extracted {len(screenshots)} screenshots.")

#         # Transcribe audio using Deepgram
#         transcription_data = await transcribe_audio(temp_video.name)
#         transcript = transcription_data["transcript"]
#         words = transcription_data["words"]
#         logger.info(f"Transcript length: {len(transcript)} characters")

#     # b64_screens = [frame_to_b64(f) for f in screenshots]

#     logger.info("Video processing completed successfully.")
#     return {
#         "success": True,
#         "message": "Video processed successfully.",
#         "data": {
#             "screenshots": screenshots,
#             "count": len(screenshots),
#             "transcript": transcript,
#         },
#     }


from fastapi import APIRouter, UploadFile, File
from video_logic import get_frame
import base64
import cv2
import tempfile
import subprocess
import os
from dotenv import load_dotenv
import logging
from typing import List
from pydantic import BaseModel, Field
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage

load_dotenv()
router = APIRouter()

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("video_upload_api")


class AnalyzerResponse(BaseModel):
    timestamp: int = Field(..., description="Timestamp in seconds")
    task: str = Field(..., description="Short task name")
    description: str = Field(..., description="Detailed explanation")
    category: str = Field(..., description="Type of issue")


class AllAnalyzerResponse(BaseModel):
    issues: List[AnalyzerResponse] = Field(..., description="List of tasks/issues")


llm = ChatGoogleGenerativeAI(
    model=os.getenv("GOOGLE_API_MODEL") , api_key=os.getenv("GOOGLE_API_KEY")
)
structured_llm = llm.with_structured_output(AllAnalyzerResponse)


def split_video_into_chunks(
    video_path: str, chunk_length: int = 15, buffer: int = 2
) -> List[str]:
    """
    Splits the video into overlapping chunks with given buffer (in seconds)
    Returns list of temp file paths
    """
    import cv2

    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps
    logger.info(f"Video duration: {duration}s, fps: {fps}")

    chunk_paths = []
    start = 0
    while start < duration:
        chunk_start = max(start - buffer, 0)
        chunk_end = min(start + chunk_length + buffer, duration)
        temp_chunk = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
        temp_chunk_path = temp_chunk.name
        temp_chunk.close()

        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                video_path,
                "-ss",
                str(chunk_start),
                "-to",
                str(chunk_end),
                "-c",
                "copy",
                temp_chunk_path,
            ],
            check=True,
        )
        chunk_paths.append(temp_chunk_path)
        start += chunk_length
    cap.release()
    return chunk_paths


async def analyze_video_chunk(base64_video: str) -> List[AnalyzerResponse]:
    """
    Sends a video chunk to Gemini to detect tasks/issues.
    """
    if not base64_video:
        return []

    prompt = (
        "Analyze this office video chunk for maintenance, repairs, and cleaning issues "
        "(electrical, decor, furniture, etc.). For each issue, provide a structured list "
        "with: timestamp (when frame is stable), short task name, description, and category."
    )

    message = HumanMessage(
        content=[
            {"type": "text", "text": prompt},
            {"type": "media", "data": base64_video, "mime_type": "video/mp4"},
        ]
    )

    result = structured_llm.invoke([message])
    return result.issues if hasattr(result, "issues") else []


@router.post("/upload-video")
async def upload_video(file: UploadFile = File(...)):
    """
    Accepts full video, splits into chunks (~15s), sends each chunk to Gemini,
    and returns all detected tasks/issues with base64 screenshots.
    """
    logger.info(f"Received video upload: {file.filename}")
    content = await file.read()

    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as temp_video:
        temp_video.write(content)
        temp_video.flush()
        video_path = temp_video.name

    # Split video into 15-sec chunks with ±2 sec buffer
    chunk_paths = split_video_into_chunks(video_path, chunk_length=15, buffer=2)
    logger.info(f"Video split into {len(chunk_paths)} chunks")

    all_tasks = []
    for chunk_path in chunk_paths:
        with open(chunk_path, "rb") as f:
            b64_chunk = base64.b64encode(f.read()).decode("utf-8")
        issues = await analyze_video_chunk(b64_chunk)

        # Get actual frame for each task timestamp
        for issue in issues:
            frame = get_frame(video_path, issue.timestamp)
            b64_frame = None
            if frame is not None:

                _, buffer = cv2.imencode(".jpg", frame)
                b64_frame = base64.b64encode(buffer).decode("utf-8")

            all_tasks.append(
                {
                    "task": issue.task,
                    "description": issue.description,
                    "category": issue.category,
                    "image": b64_frame,
                }
            )

        os.remove(chunk_path)  # cleanup

    os.remove(video_path)
    logger.info(f"Video processing completed, total tasks found: {len(all_tasks)}")

    return {
        "success": True,
        "message": "Video processed successfully",
        "data": {
            "screenshots": all_tasks,
            "count": len(all_tasks),
            "transcript": "transcript",
        },
    }
