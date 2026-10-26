FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY habits ./habits
COPY mcp_server ./mcp_server
COPY tests ./tests

ENV PYTHONUNBUFFERED=1 MPLCONFIGDIR=/tmp/matplotlib
EXPOSE 8001

CMD ["python", "-m", "mcp_server.server"]
