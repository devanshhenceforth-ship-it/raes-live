# video_upload_api.py
from fastapi import APIRouter, UploadFile, File
from video_logic import extract_video_screenshots

import base64
import cv2
import tempfile
import subprocess
import os
import httpx

router = APIRouter()
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")  # set your key in env


def frame_to_b64(frame):
    _, buffer = cv2.imencode(".jpg", frame)
    return base64.b64encode(buffer).decode("utf-8")


async def transcribe_audio(video_path: str) -> str:
    """
    Extract audio from video and send to Deepgram for transcription.
    """
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as temp_audio:
        # Extract audio using ffmpeg
        subprocess.run(
            [
                "ffmpeg",
                "-i",
                video_path,
                "-vn",  # no video
                "-acodec",
                "pcm_s16le",  # WAV format
                "-ar",
                "16000",  # 16 kHz
                "-ac",
                "1",  # mono
                temp_audio.name,
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # Read audio bytes
        audio_bytes = open(temp_audio.name, "rb").read()

    url = "https://api.deepgram.com/v1/listen"
    params = {"model": "nova-3", "smart_format": "true", "punctuate": "true"}
    headers = {
        "Authorization": f"Token {DEEPGRAM_API_KEY}",
        "Content-Type": "audio/wav",
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            url, params=params, headers=headers, content=audio_bytes
        )
        resp.raise_for_status()
        data = resp.json()

    transcript = data["results"]["channels"][0]["alternatives"][0]["transcript"]
    return transcript


@router.post("/upload-video")
async def upload_video(file: UploadFile = File(...)):
    """
    Accept whole video file upload, extract screenshots and audio transcript,
    return as base64.
    """
    content = await file.read()

    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=True) as temp_video:
        temp_video.write(content)
        temp_video.flush()

        # Extract screenshots directly from temp file
        screenshots = extract_video_screenshots(temp_video.name, every_n_frames=60)

        # Transcribe audio using Deepgram
        transcript = await transcribe_audio(temp_video.name)

    b64_screens = [frame_to_b64(f) for f in screenshots]

    return {
        "success": True,
        "message": "Video processed successfully.",
        "data": {
            "screenshots": screenshots,
            "count": len(b64_screens),
            "transcript": transcript,
        },
    }
