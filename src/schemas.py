from pydantic import BaseModel, Field
from typing import List, Optional

class VideoEvent(BaseModel):
    timestamp: int
    task: str
    description: str
    category: str

class AudioEvent(BaseModel):
    task_detected: bool
    transcript: Optional[str]
    video_events: List[VideoEvent] = []

class FrameSelection(BaseModel):
    index: int