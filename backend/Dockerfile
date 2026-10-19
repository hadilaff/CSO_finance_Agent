FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    graphviz \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# All Python source files are now inside backend/
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN pip install --no-cache-dir \
    fastapi>=0.111.0 \
    uvicorn[standard]>=0.29.0 \
    python-multipart>=0.0.9

COPY backend/agent.py backend/briefing.py backend/config.py backend/deck.py \
     backend/forecasting.py backend/logigramme.py backend/market_data.py \
     backend/rag.py backend/search.py backend/voice.py backend/auth.py ./

COPY backend/main.py ./main.py

RUN mkdir -p /app/.chroma /app/briefings /app/files

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
