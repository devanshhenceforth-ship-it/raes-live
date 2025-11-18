# Use Python 3.13 (slim)
FROM python:3.13-slim

# Set working directory
WORKDIR /app

# Copy requirements
COPY requirements.txt .

# Install dependencies + ffmpeg
RUN apt-get update && apt-get install -y \
        ffmpeg \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy all app source code
COPY . .

# Expose FastAPI port
EXPOSE 9003

# Run the FastAPI app
CMD ["python3", "main.py"]
