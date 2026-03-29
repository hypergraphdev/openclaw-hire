FROM python:3.11-slim

WORKDIR /app

# Install Docker CLI (for managing agent containers via host socket)
RUN apt-get update && apt-get install -y --no-install-recommends \
    docker.io git \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8012

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8012"]
