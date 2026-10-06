FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt requirements-core.txt ./
RUN pip install --no-cache-dir -r requirements.txt
# bake both embedding models into the image: no download at startup, works offline
RUN python -c "from sentence_transformers import SentenceTransformer as S; \
[S(m) for m in ('sentence-transformers/all-MiniLM-L6-v2', 'BAAI/bge-small-en-v1.5')]"
COPY . .
ENV PYTHONPATH=/app PYTHONUNBUFFERED=1
EXPOSE 8000 8501
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
