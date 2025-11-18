# # import subprocess
# # from fastapi import APIRouter, FastAPI
# # from pathlib import Path
# # from collections import deque
# # import asyncio
# # import cv2
# # from google.genai import Client
# # import os
# # import base64
# # from dotenv import load_dotenv
# # from langchain_core.messages import HumanMessage
# # from .schemas import AudioEvent, FrameSelection
# # from langchain_google_genai import ChatGoogleGenerativeAI

# # import socketio  # <-- new import

# # load_dotenv()
# # # router = APIRouter()

# # # ----------------- BUFFERS -----------------
# # CHUNK_FILE = Path("chunk.webm")
# # AUDIO_FILE = Path("audio.wav")
# # FRAME_DIR = Path("frames/")
# # FRAME_DIR.mkdir(exist_ok=True)

# # video_cache = deque(maxlen=10)
# # audio_cache = deque(maxlen=5)

# # client = Client(api_key=os.getenv("GOOGLE_API_KEY"))

# # # analyzer lock
# # analyzing_audio = False

# # # Setup Gemini
# # llm = ChatGoogleGenerativeAI(
# #     model="gemini-2.5-flash",
# #     api_key=os.getenv("GOOGLE_API_KEY"),
# # )
# # audio_llm = llm.with_structured_output(AudioEvent)
# # video_llm = llm.with_structured_output(FrameSelection)
# # # ----------------- AUDIO ANALYSIS -----------------
# # async def analyze_audio(audio_bytes: bytes):
# #     print(f"[AUDIO] Analyzing audio bytes = {len(audio_bytes)}")
# #     if not audio_bytes:
# #         return False, None

# #     prompt = """
# #     "Analyze the attached audio for maintenance, repairs, and cleaning issues (electrical, decor, furniture, etc.). "
# #     Transcribe the audio. If it contains a task, return:
# #     - task_detected = true
# #     - list of VideoEvent items
# #     Otherwise return task_detected = false.
# #     """
# #     try:
# #         message = HumanMessage(
# #             content=[
# #                 {"type": "text", "text": prompt},
# #                 {"type": "media", "data": audio_bytes, "mime_type": "audio/wav"},
# #             ]
# #         )
# #         data = audio_llm.invoke([message])
# #     except Exception as e:
# #         print("[AUDIO] ERROR calling Gemini:", e)
# #         return False, None

# #     print("[AUDIO] Parsed response:", data)
# #     return data.task_detected, data

# # # ----------------- VIDEO PROCESSING -----------------
# # async def process_video_chunk(video_buffer: bytearray):
# #     if not video_buffer:
# #         return

# #     CHUNK_FILE.write_bytes(video_buffer)
# #     video_buffer.clear()

# #     # extract audio
# #     subprocess.run([
# #         "ffmpeg", "-y", "-i", str(CHUNK_FILE),
# #         "-vn", "-acodec", "pcm_s16le",
# #         "-ar", "16000", "-ac", "1", str(AUDIO_FILE)
# #     ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

# #     if AUDIO_FILE.exists():
# #         audio_bytes = AUDIO_FILE.read_bytes()
# #         audio_cache.append(audio_bytes)
# #     else:
# #         print("[VIDEO] audio.wav not found, skipping audio analysis")

# #     # clean frames
# #     for f in FRAME_DIR.glob("frame-*.jpg"):
# #         f.unlink()

# #     # extract frames
# #     subprocess.run([
# #         "ffmpeg", "-y", "-i", str(CHUNK_FILE),
# #         "-vf", "fps=1", str(FRAME_DIR / "frame-%03d.jpg")
# #     ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

# #     frame_files = sorted(FRAME_DIR.glob("frame-*.jpg"))
# #     for frame_file in frame_files:
# #         frame = cv2.imread(str(frame_file))
# #         if frame is not None:
# #             video_cache.append((frame, 0))

# # # ----------------- VIDEO ANALYSIS -----------------
# # async def analyze_video():
# #     global analyzing_audio
# #     print("[VIDEO_ANALYZER] Started")

# #     while True:
# #         if analyzing_audio:
# #             await asyncio.sleep(0.2)
# #             continue

# #         if not audio_cache or not video_cache:
# #             await asyncio.sleep(0.3)
# #             continue

# #         analyzing_audio = True
# #         frames_to_check = list(video_cache)
# #         audio_bytes = b"".join(audio_cache)

# #         task_triggered, data = await analyze_audio(audio_bytes)

# #         if task_triggered:
# #             images = []
# #             for frame, _ in frames_to_check:
# #                 _, b = cv2.imencode(".jpg", frame)
# #                 images.append(b.tobytes())

# #             try:
# #                 message = HumanMessage(
# #                 contents=[
# #                             {"text": "Return JSON: { index: number } for best frame."},
# #                             *[
# #                                 {"inline_data": {"data": img, "mime_type": "image/jpeg"}}
# #                             for img in images
# #                         ]
# #                     ],
# #         )
# #                 response = video_llm.invoke([message])
# #                 # response = client.models.generate_content(
# #                 #     model="gemini-2.5-flash",
# #                 #     contents=[
# #                 #         {"text": "Return JSON: { index: number } for best frame."},
# #                 #         *[
# #                 #             {"inline_data": {"data": img, "mime_type": "image/jpeg"}}
# #                 #             for img in images
# #                 #         ]
# #                 #     ],
# #                 #     config={
# #                 #         "response_mime_type": "application/json",
# #                 #         "response_json_schema": FrameSelection.model_json_schema()
# #                 #     }
# #                 # )
# #             except Exception as e:
# #                 print("[VIDEO_ANALYZER] Gemini frame error:", e)
# #                 analyzing_audio = False
# #                 continue

# #             try:
# #                 result = FrameSelection.model_validate_json(response)
# #                 idx = result.index
# #             except:
# #                 print("[VIDEO_ANALYZER] Bad frame index:", response.text)
# #                 analyzing_audio = False
# #                 continue

# #             chosen_frame, _ = frames_to_check[idx]
# #             _, buf = cv2.imencode(".jpg", chosen_frame)
# #             img_b64 = base64.b64encode(buf).decode()

# #             # broadcast via Socket.IO
# #             await sio.emit('task_detected', {
# #                 "image_base64": img_b64,
# #                 "meta": data
# #             })

# #         analyzing_audio = False
# #         await asyncio.sleep(0.2)

# # # ----------------- SOCKET.IO EVENT -----------------
# # # ----------------- SOCKET.IO SETUP -----------------
# # sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")

# # # global flag for analyzer
# # analyzer_started = False
# # sio.video_buffers = {}  # per-client buffers

# # # ----------------- SOCKET.IO EVENT -----------------
# # @sio.event
# # async def connect(sid, environ):
# #     global analyzer_started
# #     print(f"[Socket.IO] Client connected: {sid}")
# #     if not analyzer_started:
# #         analyzer_started = True
# #         asyncio.create_task(analyze_video())

# # @sio.event
# # async def disconnect(sid):
# #     print(f"[Socket.IO] Client disconnected: {sid}")
# #     # clean up buffer
# #     sio.video_buffers.pop(sid, None)

# # @sio.event
# # async def video_chunk(sid, data):
# #     import base64
# #     chunk_bytes = base64.b64decode(data)

# #     # store in temporary buffer per client
# #     if sid not in sio.video_buffers:
# #         sio.video_buffers[sid] = bytearray()
# #     sio.video_buffers[sid].extend(chunk_bytes)

# #     # process chunk
# #     await process_video_chunk(sio.video_buffers[sid])


# import subprocess
# from fastapi import FastAPI
# from pathlib import Path
# from collections import deque
# import asyncio
# import cv2
# from google.genai import Client
# import os
# import base64
# from dotenv import load_dotenv
# from langchain_core.messages import HumanMessage
# from .schemas import AudioEvent, FrameSelection
# from langchain_google_genai import ChatGoogleGenerativeAI
# import socketio

# load_dotenv()

# # ----------------- BUFFERS -----------------
# CHUNK_FILE = Path("chunk.webm")
# AUDIO_FILE = Path("audio.wav")
# FRAME_DIR = Path("frames/")
# FRAME_DIR.mkdir(exist_ok=True)

# video_cache = deque(maxlen=10)
# audio_cache = deque(maxlen=5)

# client = Client(api_key=os.getenv("GOOGLE_API_KEY"))

# analyzing_audio = False

# # Setup Gemini
# llm = ChatGoogleGenerativeAI(
#     model="gemini-2.5-flash",
#     api_key=os.getenv("GOOGLE_API_KEY"),
# )
# audio_llm = llm.with_structured_output(AudioEvent)
# video_llm = llm.with_structured_output(FrameSelection)

# # ----------------- AUDIO ANALYSIS -----------------
# async def analyze_audio(audio_bytes: bytes):
#     print(f"[AUDIO] Analyzing audio bytes = {len(audio_bytes)}")
#     if not audio_bytes:
#         print("[AUDIO] No audio bytes to analyze")
#         return False, None

#     prompt = """
#     Analyze the attached audio for maintenance, repairs, and cleaning issues.
#     Transcribe the audio. If it contains a task, return:
#     - task_detected = true
#     - list of VideoEvent items
#     Otherwise return task_detected = false.
#     """
#     try:
#         message = HumanMessage(
#             content=[
#                 {"type": "text", "text": prompt},
#                 {"type": "media", "data": audio_bytes, "mime_type": "audio/wav"},
#             ]
#         )
#         data = audio_llm.invoke([message])
#     except Exception as e:
#         print("[AUDIO] ERROR calling Gemini:", e)
#         return False, None

#     print("[AUDIO] Parsed response:", data)
#     return data.task_detected, data

# # ----------------- VIDEO PROCESSING -----------------
# async def process_video_chunk(video_buffer: bytearray):
#     if not video_buffer:
#         print("[VIDEO] Empty video buffer, skipping")
#         return

#     print(f"[VIDEO] Writing chunk of size {len(video_buffer)} bytes to {CHUNK_FILE}")
#     CHUNK_FILE.write_bytes(video_buffer)
#     video_buffer.clear()

#     # extract audio
#     print("[VIDEO] Extracting audio from video chunk")
#     try:
#         result = subprocess.run([
#             "ffmpeg", "-y", "-i", str(CHUNK_FILE),
#             "-vn", "-acodec", "pcm_s16le",
#             "-ar", "16000", "-ac", "1", str(AUDIO_FILE)
#         ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)

#         if result.returncode != 0:
#             print(f"[VIDEO] ffmpeg audio extraction failed:\n{result.stderr}")
#         elif AUDIO_FILE.exists():
#             audio_bytes = AUDIO_FILE.read_bytes()
#             audio_cache.append(audio_bytes)
#             print(f"[VIDEO] Audio bytes appended, total cached: {len(audio_cache)}")
#         else:
#             print("[VIDEO] audio.wav not created, skipping audio analysis")
#     except Exception as e:
#         print("[VIDEO] Exception during audio extraction:", e)

#     # clean frames
#     for f in FRAME_DIR.glob("frame-*.jpg"):
#         f.unlink()

#     # extract frames
#     print("[VIDEO] Extracting frames from video chunk")
#     try:
#         result = subprocess.run([
#             "ffmpeg", "-y", "-i", str(CHUNK_FILE),
#             "-vf", "fps=1", str(FRAME_DIR / "frame-%03d.jpg")
#         ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)

#         if result.returncode != 0:
#             print(f"[VIDEO] ffmpeg frame extraction failed:\n{result.stderr}")

#         frame_files = sorted(FRAME_DIR.glob("frame-*.jpg"))
#         for frame_file in frame_files:
#             frame = cv2.imread(str(frame_file))
#             if frame is not None:
#                 video_cache.append((frame, 0))
#             else:
#                 print(f"[VIDEO] Failed to read frame: {frame_file}")

#         print(f"[VIDEO] Frames cached: {len(video_cache)}")
#     except Exception as e:
#         print("[VIDEO] Exception during frame extraction:", e)

# # ----------------- VIDEO ANALYSIS -----------------
# async def analyze_video():
#     global analyzing_audio
#     print("[VIDEO_ANALYZER] Started")

#     while True:
#         if analyzing_audio:
#             await asyncio.sleep(0.2)
#             continue

#         if not audio_cache or not video_cache:
#             await asyncio.sleep(0.3)
#             continue

#         analyzing_audio = True
#         print(f"[VIDEO_ANALYZER] Running analysis on {len(audio_cache)} audio chunks and {len(video_cache)} frames")
#         frames_to_check = list(video_cache)
#         audio_bytes = b"".join(audio_cache)

#         task_triggered, data = await analyze_audio(audio_bytes)

#         if task_triggered:
#             print("[VIDEO_ANALYZER] Task detected, processing frames")
#             images = []
#             for frame, _ in frames_to_check:
#                 _, b = cv2.imencode(".jpg", frame)
#                 images.append(b.tobytes())

#             try:
#                 message = HumanMessage(
#                     contents=[
#                         {"text": "Return JSON: { index: number } for best frame."},
#                         *[
#                             {"inline_data": {"data": img, "mime_type": "image/jpeg"}}
#                             for img in images
#                         ]
#                     ],
#                 )
#                 response = video_llm.invoke([message])
#             except Exception as e:
#                 print("[VIDEO_ANALYZER] Gemini frame error:", e)
#                 analyzing_audio = False
#                 continue

#             try:
#                 result = FrameSelection.model_validate_json(response)
#                 idx = result.index
#                 print(f"[VIDEO_ANALYZER] Chosen frame index: {idx}")
#             except Exception as e:
#                 print("[VIDEO_ANALYZER] Bad frame index:", response)
#                 analyzing_audio = False
#                 continue

#             chosen_frame, _ = frames_to_check[idx]
#             _, buf = cv2.imencode(".jpg", chosen_frame)
#             img_b64 = base64.b64encode(buf).decode()

#             print("[VIDEO_ANALYZER] Emitting task_detected event via Socket.IO")
#             await sio.emit('task_detected', {
#                 "image_base64": img_b64,
#                 "meta": data
#             })

#         analyzing_audio = False
#         await asyncio.sleep(0.2)

# # ----------------- SOCKET.IO SETUP -----------------
# sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")
# analyzer_started = False
# sio.video_buffers = {}

# # ----------------- SOCKET.IO EVENTS -----------------
# @sio.event
# async def connect(sid, environ):
#     global analyzer_started
#     print(f"[Socket.IO] Client connected: {sid}")
#     if not analyzer_started:
#         analyzer_started = True
#         asyncio.create_task(analyze_video())

# @sio.event
# async def disconnect(sid):
#     print(f"[Socket.IO] Client disconnected: {sid}")
#     sio.video_buffers.pop(sid, None)

# @sio.event
# async def video_chunk(sid, data):
#     print(f"[Socket.IO] Received video_chunk from {sid} with data_length: {len(data)}")
#     import base64
#     chunk_bytes = base64.b64decode(data)

#     if sid not in sio.video_buffers:
#         sio.video_buffers[sid] = bytearray()
#     sio.video_buffers[sid].extend(chunk_bytes)
#     print(f"[Socket.IO] Received chunk of size {len(chunk_bytes)} from {sid}, total buffer: {len(sio.video_buffers[sid])}")

#     await process_video_chunk(sio.video_buffers[sid])

