FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MODEL_PATH=/app/artifacts/model.joblib

WORKDIR /app

RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY data ./data
COPY src ./src

ARG MODEL_VERSION=container-local
RUN python src/train.py --check-auc 0.78 --model-version "${MODEL_VERSION}" \
    && chown -R appuser:appgroup /app

USER appuser
EXPOSE 8000

CMD ["uvicorn", "src.score:app", "--host", "0.0.0.0", "--port", "8000"]
