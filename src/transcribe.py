import tempfile
from faster_whisper import WhisperModel

# Load Whisper model globally (CPU-friendly)
whisper_model = WhisperModel("tiny", device="cpu")  # choose "tiny", "base", "small" as needed

async def transcribe_video_with_whisper(video_bytes: bytes):
    """
    Transcribe video bytes to text with timestamps using Whisper.
    Returns a list of segments: [{'start': float, 'end': float, 'text': str}, ...]
    """
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp_video:
        tmp_video.write(video_bytes)
        tmp_video.flush()
        video_path = tmp_video.name

    # Run transcription
    segments, _ = whisper_model.transcribe(video_path)
    
    # Format result
    transcript = []
    for seg in segments:
        transcript.append({
            "start": seg.start,
            "end": seg.end,
            "text": seg.text
        })

    return transcript
