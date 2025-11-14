import cv2
import base64
import random
import asyncio
import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from video_upload_api import router as upload_router
import os
from dotenv import load_dotenv
import json
import websockets

load_dotenv()

DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")

app = FastAPI(title="Video Analyzer WS")
app.include_router(upload_router)
MAX_FRAMES = 50

def decode_b64_frame(frame_b64: str) -> np.ndarray:
    data = base64.b64decode(frame_b64)
    np_arr = np.frombuffer(data, np.uint8)
    return cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

def encode_frame_to_b64(frame: np.ndarray) -> str:
    _, buffer = cv2.imencode(".jpg", frame)
    return base64.b64encode(buffer).decode("utf-8")

@app.websocket("/ws/video")
async def video_socket(ws: WebSocket):
    await ws.accept()
    frames = []

    uri = (
        "wss://api.deepgram.com/v1/listen"
        "?encoding=linear16&sample_rate=16000&model=nova-3&interim_results=true"
    )
    headers = {
        "Authorization": f"Token {DEEPGRAM_API_KEY}"
    }

    async with websockets.connect(uri, extra_headers=headers) as dg_ws:

        async def send_audio():
            try:
                while True:
                    msg = await ws.receive_json()
                    print("msg_type", msg.keys())
                    audio_b64 = msg.get("audio")
                    if audio_b64:
                        audio_bytes = base64.b64decode(audio_b64)
                        await dg_ws.send(audio_bytes)

                    frame_b64 = msg.get("frame")
                    if frame_b64:
                        frame = decode_b64_frame(frame_b64)
                        frames.append(frame)
                        if len(frames) > MAX_FRAMES:
                            frames.pop(0)
            except WebSocketDisconnect:
                pass

        async def receive_transcript():
            try:
                async for message in dg_ws:
                    data = json.loads(message)
                    if "channel" in data and data["channel"]["alternatives"]:
                        transcript = data["channel"]["alternatives"][0]["transcript"]
                        if transcript.strip():
                            await ws.send_json({"transcript": transcript})
            except websockets.ConnectionClosed:
                pass

        async def send_random_frames():
            while True:
                await asyncio.sleep(2)
                if frames:
                    frame = random.choice(frames)
                    await ws.send_json({"screenshot": encode_frame_to_b64(frame)})

        send_audio_task = asyncio.create_task(send_audio())
        receive_transcript_task = asyncio.create_task(receive_transcript())
        send_frames_task = asyncio.create_task(send_random_frames())

        done, pending = await asyncio.wait(
            [send_audio_task, receive_transcript_task, send_frames_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

        for task in pending:
            task.cancel()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        workers=1,
    )
