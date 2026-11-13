FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN pip install --no-cache-dir torch torchaudio --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir whisperlivekit

# Télécharge le modèle pendant le build (sans bloquer le build si le téléchargement échoue :
# il sera alors récupéré au premier lancement)
ARG WLK_MODEL=small
RUN wlk pull faster-whisper:${WLK_MODEL} || echo "Préchargement du modèle impossible : il sera téléchargé au premier lancement."

EXPOSE 8000

# Entrée PCM 16 kHz (envoyée par l'application), moteur faster-whisper avec LocalAgreement (rapide sur CPU)
ENTRYPOINT ["wlk", "--host", "0.0.0.0", "--port", "8000", "--pcm-input", "--backend", "faster-whisper", "--backend-policy", "localagreement"]
CMD ["--model", "small", "--language", "fr"]
