FROM python:3.11-slim

# --- Install system deps needed by OpenCV & FFmpeg ----
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libsm6 \
    libxext6 \
    wget \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirement list
COPY requirements.txt .

# Install all python deps
RUN pip install --no-cache-dir -r requirements.txt

# Copy rest of application
COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
