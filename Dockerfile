FROM python:3.11-slim

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . .

# Data directory (mounted as volume in production)
RUN mkdir -p data/users data/shared/profiles

# Default: run bot. Override in docker-compose for api service.
CMD ["python3", "bot/main.py"]
