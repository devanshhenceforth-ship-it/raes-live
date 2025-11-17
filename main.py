from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.api import router as stream_router
import uvicorn

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins= ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True  # if you need cookies / credentials
)

# register your streaming route
app.include_router(stream_router)


def main():
    print("Starting server on http://0.0.0.0:8000")
    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=8000,
        reload=True
    )


if __name__ == "__main__":
    main()
