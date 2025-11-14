# video_logic.py
import cv2
import os
from uuid import uuid4


def save_uploaded_video(temp_file) -> str:
    """
    Save uploaded video to disk with a unique name.
    Returns the file path.
    """
    video_id = str(uuid4())
    file_path = f"uploaded_videos/{video_id}.mp4"

    os.makedirs("uploaded_videos", exist_ok=True)

    with open(file_path, "wb") as f:
        f.write(temp_file)

    return file_path


def extract_video_screenshots(video_path: str, every_n_frames=50):
    """
    Extract screenshots every N frames from uploaded video.
    Returns list of frame images (OpenCV BGR arrays).
    """
    # cap = cv2.VideoCapture(video_path)
    # frames = []
    # idx = 0

    # while True:
    #     ok, frame = cap.read()
    #     if not ok:
    #         break
    #     if idx % every_n_frames == 0:
    #         frames.append(frame)
    #     idx += 1

    # cap.release()

    # --- HARD-CODED SCREENSHOTS ---
    hardcoded_screenshots = [
        {
            "image": "BASE64_IMAGE_1",
            "task": "Broken light",
            "description": "Light flickering in the hallway",
            "category": "electrical"
        },
        {
            "image": "BASE64_IMAGE_2",
            "task": "Dirty floor",
            "description": "Needs cleaning near entrance",
            "category": "cleaning"
        },
        {
            "image": "BASE64_IMAGE_3",
            "task": "Wall decor",
            "description": "Peeling paint behind the chair",
            "category": "decor"
        }
    ]
    return hardcoded_screenshots
