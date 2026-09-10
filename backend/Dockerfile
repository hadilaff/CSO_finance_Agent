FROM python:3.11-slim

# System deps: graphviz for logigramme, curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
    graphviz \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements from project root and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install FastAPI + uvicorn (not in root requirements.txt — backend only)
RUN pip install --no-cache-dir \
    fastapi>=0.111.0 \
    uvicorn[standard]>=0.29.0 \
    python-multipart>=0.0.9

# Copy all project source files
COPY agent.py briefing.py config.py deck.py forecasting.py \
     logigramme.py market_data.py rag.py search.py voice.py auth.py ./

# Copy backend entrypoint
COPY backend/main.py ./main.py

# Create directories that modules expect at runtime
RUN mkdir -p /app/.chroma /app/briefings /app/files

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
