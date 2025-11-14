# video_upload_api.py
from fastapi import APIRouter, UploadFile, File
from video_logic import save_uploaded_video, extract_video_screenshots

import base64
import cv2

router = APIRouter()


def frame_to_b64(frame):
    _, buffer = cv2.imencode(".jpg", frame)
    return base64.b64encode(buffer).decode("utf-8")


@router.post("/upload-video")
async def upload_video(file: UploadFile = File(...)):
    """
    Accept whole video file upload, save it,
    extract some screenshots, return as base64.
    """
    content = await file.read()
    # saved_path = save_uploaded_video(content)

    screenshots = extract_video_screenshots("saved_path", every_n_frames=60)

    # b64_screens = [frame_to_b64(f) for f in screenshots]

    return {
        "success": True,
        "message": "Video processed successfully.",
        "data": {"screenshots": screenshots, "count": len(screenshots)},
    }
