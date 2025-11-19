# import tempfile
# from faster_whisper import WhisperModel

# # Load Whisper model globally (CPU-friendly)
# whisper_model = WhisperModel("tiny", device="cpu")  # choose "tiny", "base", "small" as needed
# async def transcribe_video_with_whisper(video_bytes: bytes) -> str:
#     """
#     Transcribe video bytes to a single text string using Whisper.
#     Returns an empty string if transcription fails.
#     """
#     try:
#         with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp_video:
#             tmp_video.write(video_bytes)
#             tmp_video.flush()
#             video_path = tmp_video.name

#         # Run transcription
#         segments, _ = whisper_model.transcribe(video_path)
        
#         # Combine all segment texts into a single string
#         transcript_text = " ".join(seg.text for seg in segments)
#         return transcript_text

#     except Exception as e:
#         print("[WHISPER] Transcription failed:", e)
#         return ""

import asyncio
import subprocess
import httpx
import logging
import os
from dotenv import load_dotenv
load_dotenv()

DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")
if not DEEPGRAM_API_KEY:
    raise RuntimeError("Set DEEPGRAM_API_KEY env var")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("video_transcription")


async def transcribe_video_bytes(video_bytes: bytes) -> dict:
    """
    Transcribe video bytes using Deepgram.
    Returns dict: {'transcript': str, 'words': [{'id','word','start','end'},...]}
    """
    try:
        # Run ffmpeg in a subprocess to convert video bytes -> WAV bytes
        ffmpeg_cmd = [
            "ffmpeg",
            "-i", "pipe:0",        # input from stdin
            "-vn",                 # no video
            "-acodec", "pcm_s16le",
            "-ar", "16000",
            "-ac", "1",
            "-f", "wav",
            "pipe:1"               # output to stdout
        ]

        logger.info("Extracting audio from video in-memory...")
        proc = await asyncio.create_subprocess_exec(
            *ffmpeg_cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await proc.communicate(input=video_bytes)

        if proc.returncode != 0:
            logger.error(f"ffmpeg failed: {stderr.decode()}")
            return {"transcript": "", "words": []}

        audio_bytes = stdout

        if not audio_bytes:
            logger.warning("No audio extracted from video")
            return {"transcript": "", "words": []}

        # Send audio to Deepgram
        url = "https://api.deepgram.com/v1/listen"
        headers = {
            "Authorization": f"Token {DEEPGRAM_API_KEY}",
            "Content-Type": "audio/wav",
        }
        params = {"model": "nova-3", "smart_format": "true", "punctuate": "true"}

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, headers=headers, params=params, content=audio_bytes)
            resp.raise_for_status()
            data = resp.json()

        alt = data["results"]["channels"][0]["alternatives"][0]
        transcript = alt.get("transcript", "")

        return  transcript

    except Exception as e:
        logger.error(f"[DEEPGRAM] Transcription failed: {e}")
        return ""
