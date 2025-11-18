import tempfile
from faster_whisper import WhisperModel

# Load Whisper model globally (CPU-friendly)
whisper_model = WhisperModel("tiny", device="cpu")  # choose "tiny", "base", "small" as needed
async def transcribe_video_with_whisper(video_bytes: bytes) -> str:
    """
    Transcribe video bytes to a single text string using Whisper.
    Returns an empty string if transcription fails.
    """
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp_video:
            tmp_video.write(video_bytes)
            tmp_video.flush()
            video_path = tmp_video.name

        # Run transcription
        segments, _ = whisper_model.transcribe(video_path)
        
        # Combine all segment texts into a single string
        transcript_text = " ".join(seg.text for seg in segments)
        return transcript_text

    except Exception as e:
        print("[WHISPER] Transcription failed:", e)
        return ""
