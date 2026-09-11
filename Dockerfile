FROM python:3.11-slim

WORKDIR /app

# Install system dependencies: graphviz for logigramme generation
RUN apt-get update && \
    apt-get install -y --no-install-recommends graphviz && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies (layer cache)
COPY requirements.txt .
RUN pip install -r requirements.txt

# Copy source code
COPY *.py ./
COPY eval/ ./eval/
COPY files/ ./files/

# Chroma persistence directory
RUN mkdir -p .chroma

EXPOSE 8501

HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health || exit 1

CMD ["streamlit", "run", "streamlit_app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true"]
