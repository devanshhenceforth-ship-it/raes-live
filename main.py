from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.api import sio
import uvicorn
import socketio

app = FastAPI()
app.mount("/socket.io", socketio.ASGIApp(sio, other_asgi_app=app))

app.add_middleware(
    CORSMiddleware,
    allow_origins= ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True  
)

# register your streaming route
# app.include_router(stream_router)


def main():
    print("Starting server on http://0.0.0.0:9003")
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=9003,
        reload=True
    )


if __name__ == "__main__":
    main()
