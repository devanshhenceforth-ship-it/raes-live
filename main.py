# app.py
import cv2
import base64
import random
import asyncio
import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from video_upload_api import router as upload_router

app = FastAPI(title="Video Analyzer WS")
app.include_router(upload_router)
# Store last N frames in memory
MAX_FRAMES = 50


def decode_b64_frame(frame_b64: str) -> np.ndarray:
    """Decode base64 -> OpenCV image."""
    data = base64.b64decode(frame_b64)
    np_arr = np.frombuffer(data, np.uint8)
    return cv2.imdecode(np_arr, cv2.IMREAD_COLOR)


def encode_frame_to_b64(frame: np.ndarray) -> str:
    """Encode OpenCV frame to base64."""
    _, buffer = cv2.imencode(".jpg", frame)
    return base64.b64encode(buffer).decode("utf-8")


@app.websocket("/ws/video")
async def video_socket(ws: WebSocket):
    await ws.accept()
    frames = []

    async def send_random_frames():
        """Periodically send random frame back."""
        while True:
            await asyncio.sleep(2)  # send every 2s
            if frames:
                frame = random.choice(frames)
                await ws.send_json({"screenshot": encode_frame_to_b64(frame)})

    # Background task to send frames
    task = asyncio.create_task(send_random_frames())

    try:
        while True:
            msg = await ws.receive_json()
            b64 = msg.get("frame")
            if b64:
                frame = decode_b64_frame(b64)
                frames.append(frame)
                if len(frames) > MAX_FRAMES:
                    frames.pop(0)

    except WebSocketDisconnect:
        task.cancel()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,  
        workers=1,
    )
