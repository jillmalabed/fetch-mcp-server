FROM python:3.12-slim

WORKDIR /app

# Install dependencies first so Docker can cache this layer when only
# server.py changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .

# Render (and most container hosts) inject $PORT; default to 8000 for
# local `docker run`.
ENV MCP_TRANSPORT=streamable-http
ENV PORT=8000
EXPOSE 8000

CMD ["python", "server.py"]
