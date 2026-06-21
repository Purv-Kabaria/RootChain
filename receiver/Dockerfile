FROM python:3.11-slim AS base

WORKDIR /app

RUN addgroup --system rootchain && adduser --system --group rootchain

COPY receiver/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY receiver/main.py ./receiver/main.py

RUN chown -R rootchain:rootchain /app
USER rootchain

ENV ROOTCHAIN_LOG_FORMAT=json
ENV ROOTCHAIN_LOG_LEVEL=INFO

EXPOSE 8080

CMD ["python", "-m", "uvicorn", "receiver.main:app", "--host", "0.0.0.0", "--port", "8080"]
