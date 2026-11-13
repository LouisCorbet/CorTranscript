"""Précharge le modèle Whisper du mode par morceaux pendant le build Docker."""
import os
from faster_whisper import WhisperModel

model = os.environ.get("WHISPER_MODEL", "small")
WhisperModel(model, device="cpu", compute_type="int8")
print("Modèle Whisper prêt :", model)
