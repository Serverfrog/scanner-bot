FROM python:3.12-bookworm

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# bots folder into the container
COPY bots/ ./bots/

WORKDIR /app/bots
# Default entrypoint for attbot.py websocket
CMD ["python", "attbot.py"]