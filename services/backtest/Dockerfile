FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY engine ./engine
COPY mcp_server ./mcp_server
COPY tests ./tests
COPY sample ./sample

ENV BACKTEST_DATA_DIR=/data PYTHONUNBUFFERED=1
VOLUME /data
EXPOSE 8000 8001

CMD ["python", "-m", "engine.serve"]
