FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY catlife ./catlife
COPY mcp_server ./mcp_server
COPY tests ./tests

ENV PYTHONUNBUFFERED=1
EXPOSE 8000 8001

CMD ["python", "-m", "catlife.serve"]
