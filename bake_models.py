"""Télécharge le modèle Whisper pendant le build de l'image (et non au premier lancement)."""
import os

import whisperx

model = os.environ.get("WHISPER_MODEL", "small")
try:
    whisperx.load_model(model, "cpu", compute_type="int8", vad_method="silero")
except TypeError:  # anciennes versions de whisperx
    whisperx.load_model(model, "cpu", compute_type="int8")
print("Modèle Whisper prêt :", model)
