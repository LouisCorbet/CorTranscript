FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg git curl ca-certificates bzip2 \
    && rm -rf /var/lib/apt/lists/*

# DeepFilterNet (réduction de bruit) : binaire autonome, sans dépendance Python
RUN ARCH=$(uname -m) && \
    if [ "$ARCH" = "aarch64" ]; then F=deep-filter-0.5.6-aarch64-unknown-linux-gnu; \
    else F=deep-filter-0.5.6-x86_64-unknown-linux-musl; fi && \
    curl -fsSL -o /usr/local/bin/deep-filter \
      https://github.com/Rikorose/DeepFilterNet/releases/download/v0.5.6/$F && \
    chmod +x /usr/local/bin/deep-filter

WORKDIR /app

RUN pip install --no-cache-dir torch torchaudio --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir whisperx fastapi "uvicorn[standard]" sherpa-onnx

# Modèle de streaming réel (sherpa-onnx), embarqué dans l'image
ARG SHERPA_MODEL=sherpa-onnx-streaming-zipformer-fr-kroko-2025-08-06
RUN mkdir -p /models/sherpa && \
    curl -fsSL https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/${SHERPA_MODEL}.tar.bz2 \
    | tar xj -C /models/sherpa --strip-components=1

# Modèle Whisper (et détecteur de voix), téléchargés au build pour être prêts au premier lancement
ARG WHISPER_MODEL=small
COPY bake_models.py /app/
RUN WHISPER_MODEL=${WHISPER_MODEL} python bake_models.py

COPY app.py index.html /app/

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
