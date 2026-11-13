import asyncio
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import traceback
import wave
from concurrent.futures import ThreadPoolExecutor
from collections import OrderedDict
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
import websockets
import whisperx
from fastapi import FastAPI, HTTPException, Request, Response, WebSocket
from fastapi.responses import FileResponse

# ---------------------------------------------------------------- configuration
MODEL = os.getenv("WHISPER_MODEL", "small")
LANG = os.getenv("WHISPER_LANGUAGE", "fr")
DEVICE = os.getenv("WHISPER_DEVICE", "cpu")
COMPUTE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
APP_DIR = Path(__file__).resolve().parent
BEAM_CHUNKS = int(os.getenv("WHISPER_BEAM_CHUNKS", "5"))  # qualité du mode « par morceaux »

AUDIO_DIR = Path(os.getenv("AUDIO_DIR", "/audio"))
TRANS_DIR = Path(os.getenv("TRANSCRIPTIONS_DIR", "/transcriptions"))
WLK_URL = os.getenv("WLK_URL", "ws://wlk:8000/asr")
SHERPA_DIR = Path(os.getenv("SHERPA_MODEL_DIR", "/models/sherpa"))
SHERPA_MODEL = os.getenv("SHERPA_MODEL", "")  # nom de l'archive utilisée au build (sert à l'affichage)

DF_BIN = os.getenv("DEEPFILTER_BIN", "/usr/local/bin/deep-filter")
DF_AVAILABLE = os.path.exists(DF_BIN)

SR = 16000
SILENCE_RMS = 0.01     # seuil de silence (à ajuster selon ton micro)
END_SILENCE = 0.8      # secondes de silence pour clore une phrase (mode live)
PARTIAL_EVERY = 1.5    # secondes entre deux transcriptions partielles (mode live)
MAX_UTTERANCE = 15     # secondes max avant coupure forcée (mode live)
MIN_SAVE_SECONDS = 1   # un enregistrement plus court n'est pas conservé

ID_RE = re.compile(r"^[0-9A-Za-z_\-]+$")

# ---------------------------------------------------------------- modèle Whisper (mode live)
print("Chargement du modèle Whisper…", flush=True)
kwargs = dict(
    compute_type=COMPUTE,
    language=None if LANG == "auto" else LANG,
    asr_options={"beam_size": 1},  # beaucoup plus rapide que le défaut (5)
)
try:
    model = whisperx.load_model(MODEL, DEVICE, vad_method="silero", **kwargs)
except TypeError:  # anciennes versions de whisperx
    model = whisperx.load_model(MODEL, DEVICE, **kwargs)
print("Modèle chargé.", flush=True)

_fw = None
_fw_lock = threading.Lock()


def get_fw():
    """Modèle faster-whisper brut (celui que WhisperX utilise en interne) pour le mode par morceaux."""
    global _fw
    with _fw_lock:
        if _fw is None:
            inner = getattr(model, "model", None)
            if inner is not None and hasattr(inner, "transcribe"):
                _fw = inner
            else:
                from faster_whisper import WhisperModel
                _fw = WhisperModel(MODEL, device=DEVICE, compute_type=COMPUTE)
    return _fw


executor = ThreadPoolExecutor(max_workers=1)


# ---------------------------------------------------------------- utilitaires fichiers
def read_json(path: Path, default):
    try:
        return json.loads(path.read_text("utf-8"))
    except Exception:
        return default


def write_json(path: Path, data):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), "utf-8")
    os.replace(tmp, path)


def check_id(value: str) -> str:
    if not ID_RE.match(value):
        raise HTTPException(status_code=400, detail="identifiant invalide")
    return value


def wav_duration(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as w:
            return w.getnframes() / float(w.getframerate())
    except Exception:
        return 0.0


def id_to_iso(audio_id: str):
    try:
        return datetime.strptime(audio_id[:19], "%Y-%m-%d_%H-%M-%S").isoformat()
    except ValueError:
        return None


def new_stamp(prefix: str, directory: Path, suffixes) -> str:
    base = datetime.now().strftime(f"{prefix}%Y-%m-%d_%H-%M-%S")
    name, n = base, 1
    while any((directory / f"{name}{s}").exists() for s in suffixes):
        n += 1
        name = f"{base}_{n}"
    return name


# ---------------------------------------------------------------- réduction de bruit
def denoise(audio: np.ndarray) -> np.ndarray:
    """Réduction de bruit DeepFilterNet (binaire deep-filter), audio 16 kHz mono float32."""
    with tempfile.TemporaryDirectory() as d:
        src, out_dir = os.path.join(d, "in.wav"), os.path.join(d, "out")
        with wave.open(src, "wb") as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(SR)
            f.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())
        subprocess.run([DF_BIN, "-o", out_dir, src], check=True, capture_output=True, timeout=120)
        with wave.open(os.path.join(out_dir, "in.wav"), "rb") as f:
            data = np.frombuffer(f.readframes(f.getnframes()), dtype=np.int16)
    return data.astype(np.float32) / 32768.0


def denoise_wav(data: bytes) -> bytes:
    """Débruite un fichier WAV complet (modale d'écoute comparative)."""
    with tempfile.TemporaryDirectory() as d:
        src, out_dir = os.path.join(d, "in.wav"), os.path.join(d, "out")
        with open(src, "wb") as f:
            f.write(data)
        subprocess.run([DF_BIN, "-o", out_dir, src], check=True, capture_output=True, timeout=120)
        with open(os.path.join(out_dir, "in.wav"), "rb") as f:
            return f.read()


# ================================================================ TEXTE DU MODE LIVE (modifiable)
class LiveDoc:
    """Fichier texte d'une session live : les phrases figées y sont ajoutées, les corrections de l'utilisateur le remplacent."""

    def __init__(self, path: Path):
        self.path = path
        self.finals = []  # toutes les phrases figées, dans l'ordre (numérotées à partir de 1)

    def add_final(self, text: str) -> int:
        self.finals.append(text)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(text + "\n")
        return len(self.finals)

    def apply_edit(self, text: str, upto: int):
        """Remplace le contenu par le texte corrigé. `upto` = nombre de phrases déjà affichées à l'utilisateur au moment
        de la correction : celles arrivées depuis sont remises à la suite pour ne rien perdre."""
        text = text.replace("\r\n", "\n").rstrip("\n")
        tail = self.finals[max(0, min(upto, len(self.finals))):]
        content = (text + "\n" if text else "") + "".join(t + "\n" for t in tail)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, self.path)


LIVE_DOCS = OrderedDict()  # sessions récentes, pour enregistrer les corrections


class DocSocket:
    """Enveloppe du WebSocket : {"stop": true} devient une déconnexion, ce qui laisse le moteur figer ce qui reste
    avant que la connexion soit fermée."""

    def __init__(self, ws: WebSocket):
        self._ws = ws

    async def receive(self):
        msg = await self._ws.receive()
        if msg.get("text") is not None:
            try:
                cfg = json.loads(msg["text"])
            except ValueError:
                cfg = None
            if isinstance(cfg, dict) and cfg.get("stop"):
                return {"type": "websocket.disconnect"}
        return msg

    def __getattr__(self, name):
        return getattr(self._ws, name)


# ================================================================ MODE LIVE
def transcribe_live(audio: np.ndarray, use_denoise: bool = False) -> str:
    if use_denoise:
        try:
            audio = denoise(audio)
        except Exception:
            traceback.print_exc()  # en cas d'échec, on transcrit l'audio brut
    result = model.transcribe(audio, batch_size=8)
    return " ".join(s["text"].strip() for s in result["segments"]).strip()


async def live_whisper(ws, doc: LiveDoc):
    loop = asyncio.get_running_loop()
    buf = np.zeros(0, dtype=np.float32)
    speech, silence, since_partial = False, 0, 0
    denoise_on = False
    partial_gap = PARTIAL_EVERY  # s'allonge automatiquement si le PC n'arrive pas à suivre

    async def run(kind: str):
        nonlocal partial_gap
        t0 = time.perf_counter()
        # La réduction de bruit ne s'applique qu'à la version finale (celle écrite dans le .txt)
        use_df = denoise_on and kind == "final"
        text = await loop.run_in_executor(executor, transcribe_live, buf.copy(), use_df)
        partial_gap = max(PARTIAL_EVERY, 2 * (time.perf_counter() - t0))
        if text:
            out = {"type": kind, "text": text}
            if kind == "final":
                out["n"] = doc.add_final(text)
            await ws.send_json(out)

    while True:
        msg = await ws.receive()
        if msg["type"] == "websocket.disconnect":
            break

        if msg.get("text") is not None:  # message de contrôle (ex. {"denoise": true})
            try:
                cfg = json.loads(msg["text"])
            except ValueError:
                continue
            if "denoise" in cfg:
                denoise_on = bool(cfg["denoise"]) and DF_AVAILABLE
                await ws.send_json({"type": "info", "available": DF_AVAILABLE, "denoise": denoise_on})
            continue

        data = msg.get("bytes")
        if not data:
            continue

        chunk = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
        rms = float(np.sqrt(np.mean(chunk**2))) if len(chunk) else 0.0

        if rms >= SILENCE_RMS:
            speech, silence = True, 0
        else:
            silence += len(chunk)

        buf = np.concatenate([buf, chunk])
        since_partial += len(chunk)

        if not speech:
            buf = buf[-int(0.3 * SR):]
            continue

        if silence >= END_SILENCE * SR or len(buf) >= MAX_UTTERANCE * SR:
            await run("final")
            buf = np.zeros(0, dtype=np.float32)
            speech, silence, since_partial = False, 0, 0
        elif since_partial >= partial_gap * SR:
            since_partial = 0
            await run("partial")


async def live_wlk(ws, doc: LiveDoc):
    """Pont vers un serveur WhisperLiveKit (protocole /asr, entrée PCM 16 kHz)."""
    try:
        up = await websockets.connect(f"{WLK_URL}?language={LANG}", max_size=None, open_timeout=5)
    except Exception:
        await ws.send_json({"type": "error", "text": "WhisperLiveKit est injoignable (service non démarré ?)"})
        return

    committed = 0          # nombre de lignes déjà figées (écrites dans le fichier)
    last_lines, last_buf = [], ""

    async def send_safe(obj):
        try:
            await ws.send_json(obj)
        except Exception:
            pass

    async def finalize(text: str):
        text = text.strip()
        if not text:
            return
        n = doc.add_final(text)
        await send_safe({"type": "final", "text": text, "n": n})

    async def pump():
        nonlocal committed, last_lines, last_buf
        async for raw in up:
            if isinstance(raw, bytes):
                continue
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            kind = msg.get("type")
            if kind == "config":
                continue
            if kind == "ready_to_stop":
                break
            if msg.get("status") == "error" or msg.get("error"):
                await send_safe({"type": "error", "text": str(msg.get("error") or "erreur WhisperLiveKit")})
                continue
            lines = [l for l in msg.get("lines", []) if (l.get("text") or "").strip()]
            buf = (msg.get("buffer_transcription") or "").strip()
            last_lines, last_buf = lines, buf
            # Une ligne n'est figée que lorsqu'une ligne plus récente existe (la dernière peut encore grandir).
            stable = lines[:-1]
            for line in stable[committed:]:
                await finalize(line["text"])
            committed = max(committed, len(stable))
            pending = [l["text"].strip() for l in lines[committed:]]
            await send_safe({"type": "partial", "text": " ".join([*pending, buf]).strip()})
        # fin du flux : on fige ce qui reste
        for line in last_lines[committed:]:
            await finalize(line["text"])
        committed = len(last_lines)
        await finalize(last_buf)

    pump_task = asyncio.create_task(pump())
    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            data = msg.get("bytes")
            if data:
                await up.send(data)
    finally:
        try:
            await up.send(b"")  # signal de fin d'audio
            await asyncio.wait_for(pump_task, 20)
        except Exception:
            pump_task.cancel()
        try:
            await up.close()
        except Exception:
            pass


# ---------------------------------------------------------------- streaming réel (sherpa-onnx)
sherpa_rec = None
sherpa_executor = ThreadPoolExecutor(max_workers=1)


def _pick(prefix: str):
    files = sorted(SHERPA_DIR.glob(f"{prefix}*.onnx"))
    int8 = [f for f in files if "int8" in f.name]
    return str((int8 or files)[0]) if files else None


def load_sherpa():
    global sherpa_rec
    try:
        import sherpa_onnx

        enc, dec, joi = _pick("encoder"), _pick("decoder"), _pick("joiner")
        if not (enc and dec and joi and (SHERPA_DIR / "tokens.txt").exists()):
            print("Modèle sherpa-onnx introuvable dans", SHERPA_DIR, flush=True)
            return
        sherpa_rec = sherpa_onnx.OnlineRecognizer.from_transducer(
            tokens=str(SHERPA_DIR / "tokens.txt"), encoder=enc, decoder=dec, joiner=joi,
            num_threads=2, sample_rate=SR, feature_dim=80, decoding_method="greedy_search",
            enable_endpoint_detection=True,
            rule1_min_trailing_silence=2.4,   # silence tant que rien n'est reconnu
            rule2_min_trailing_silence=0.8,   # silence qui clôt une phrase
            rule3_min_utterance_length=20.0,  # coupure forcée d'une phrase trop longue
        )
        print("Modèle de streaming sherpa-onnx chargé.", flush=True)
    except Exception:
        traceback.print_exc()
        sherpa_rec = None


def sherpa_name() -> str:
    kind = "Zipformer FR" if SHERPA_MODEL and "kroko" not in SHERPA_MODEL.lower() else "Kroko FR"
    return f"Streaming temps réel ({kind})"


def _sherpa_text(stream) -> str:
    res = sherpa_rec.get_result(stream)
    return (res if isinstance(res, str) else getattr(res, "text", "")).strip()


def _sherpa_feed(stream, samples: np.ndarray):
    stream.accept_waveform(SR, samples)
    while sherpa_rec.is_ready(stream):
        sherpa_rec.decode_stream(stream)
    text = _sherpa_text(stream)
    endpoint = sherpa_rec.is_endpoint(stream)
    if endpoint:
        sherpa_rec.reset(stream)
    return text, endpoint


def _sherpa_flush(stream) -> str:
    stream.accept_waveform(SR, np.zeros(int(0.8 * SR), dtype=np.float32))  # laisse décoder les derniers mots
    stream.input_finished()
    while sherpa_rec.is_ready(stream):
        sherpa_rec.decode_stream(stream)
    return _sherpa_text(stream)


async def live_sherpa(ws, doc: LiveDoc):
    """Vrai streaming : le texte se met à jour en continu, une phrase est figée à la première pause."""
    if sherpa_rec is None:
        await ws.send_json({"type": "error", "text": "Modèle de streaming introuvable. Réinstalle CorTranscript ou reconstruis son image Docker."})
        return
    loop = asyncio.get_running_loop()
    stream = sherpa_rec.create_stream()
    last = ""

    async def final(text: str):
        n = doc.add_final(text)
        try:
            await ws.send_json({"type": "final", "text": text, "n": n})
        except Exception:
            pass

    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            data = msg.get("bytes")
            if not data:
                continue
            samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
            text, endpoint = await loop.run_in_executor(sherpa_executor, _sherpa_feed, stream, samples)
            if endpoint:
                if text:
                    await final(text)
                await ws.send_json({"type": "partial", "text": ""})
                last = ""
            elif text != last:
                last = text
                await ws.send_json({"type": "partial", "text": text})
    finally:
        rest = await loop.run_in_executor(sherpa_executor, _sherpa_flush, stream)
        if rest:
            await final(rest)


# Pour ajouter un moteur : écrire un handler async (ws, path) et l'ajouter ici et dans /api/engines.
LIVE_HANDLERS = {"whisper": live_whisper, "sherpa": live_sherpa, "whisperlivekit": live_wlk}


# ================================================================ MODE PAR MORCEAUX : état
JOB = {"active": False, "cancel": False, "session": None, "last_session": None, "current": None, "failed": {}}
JOB_LOCK = threading.Lock()
SETTINGS = {"denoise": False}


def set_current(audio_id, progress, phase):
    with JOB_LOCK:
        JOB["current"] = None if audio_id is None else {"id": audio_id, "progress": progress, "phase": phase}


def set_progress(progress):
    with JOB_LOCK:
        if JOB["current"]:
            JOB["current"]["progress"] = progress
            JOB["current"]["phase"] = "transcribe"


def job_state():
    with JOB_LOCK:
        return {
            "active": JOB["active"],
            "cancelling": JOB["active"] and JOB["cancel"],
            "session": JOB["session"],
            "last_session": JOB["last_session"],
            "current": dict(JOB["current"]) if JOB["current"] else None,
        }


def audio_paths(audio_id: str):
    return AUDIO_DIR / f"{audio_id}.wav", AUDIO_DIR / f"{audio_id}.json"


def list_audios():
    """Tous les audios, du plus récent au plus ancien."""
    items = []
    for wav in sorted(AUDIO_DIR.glob("*.wav"), reverse=True):
        audio_id = wav.stem
        meta = read_json(AUDIO_DIR / f"{audio_id}.json", {})
        items.append({
            "id": audio_id,
            "created": id_to_iso(audio_id),
            "duration": round(wav_duration(wav), 1),
            "size": wav.stat().st_size,
            "transcribed": bool(meta.get("transcribed")),
            "session": meta.get("session"),
            "error": JOB["failed"].get(audio_id),
        })
    return items


def next_pending(include_failed=False):
    """Le plus ancien audio pas encore transcrit (sans ceux qui ont échoué pendant cette session)."""
    for wav in sorted(AUDIO_DIR.glob("*.wav")):
        audio_id = wav.stem
        if audio_id in JOB["failed"] and not include_failed:
            continue
        if not read_json(AUDIO_DIR / f"{audio_id}.json", {}).get("transcribed"):
            return audio_id
    return None


# ---------------------------------------------------------------- enregistrement des morceaux
def pcm_to_wav(part: Path, wav: Path) -> bool:
    size = part.stat().st_size // 2 * 2
    if size < SR * 2 * MIN_SAVE_SECONDS:
        part.unlink(missing_ok=True)
        return False
    tmp = wav.with_name(wav.name + ".tmp")
    with open(part, "rb") as src, wave.open(str(tmp), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        remaining = size
        while remaining > 0:
            block = src.read(min(1 << 20, remaining))
            if not block:
                break
            w.writeframes(block)
            remaining -= len(block)
    os.replace(tmp, wav)
    write_json(wav.with_suffix(".json"), {"transcribed": False, "session": None})
    part.unlink(missing_ok=True)
    return True


def recover_parts():
    """Après un arrêt brutal : transforme les enregistrements interrompus en fichiers WAV."""
    for part in AUDIO_DIR.glob("*.pcm.part"):
        audio_id = part.name[: -len(".pcm.part")]
        try:
            pcm_to_wav(part, AUDIO_DIR / f"{audio_id}.wav")
        except Exception:
            traceback.print_exc()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    TRANS_DIR.mkdir(parents=True, exist_ok=True)
    recover_parts()
    print("Serveur prêt.", flush=True)
    yield


load_sherpa()
app = FastAPI(title="CorTranscript", lifespan=lifespan)


@app.websocket("/ws/record")
async def ws_record(ws: WebSocket):
    """Reçoit l'audio en continu ; {"cut":true} ferme le morceau en cours et en ouvre un nouveau sans perte."""
    await ws.accept()
    loop = asyncio.get_running_loop()
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    cur = {"id": None, "f": None}

    def open_seg():
        audio_id = new_stamp("", AUDIO_DIR, (".wav", ".pcm.part"))
        cur["id"] = audio_id
        cur["f"] = open(AUDIO_DIR / f"{audio_id}.pcm.part", "ab", buffering=0)

    def close_seg():
        if not cur["f"]:
            return None
        cur["f"].close()
        audio_id = cur["id"]
        cur["f"], cur["id"] = None, None
        ok = pcm_to_wav(AUDIO_DIR / f"{audio_id}.pcm.part", AUDIO_DIR / f"{audio_id}.wav")
        return audio_id if ok else None

    open_seg()
    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            if msg.get("bytes"):
                cur["f"].write(msg["bytes"])
                continue
            if msg.get("text") is not None:
                try:
                    cfg = json.loads(msg["text"])
                except ValueError:
                    continue
                if cfg.get("cut"):
                    saved = await loop.run_in_executor(None, close_seg)
                    open_seg()
                    if saved:
                        await ws.send_json({"type": "saved", "id": saved})
                elif cfg.get("stop"):
                    break
    finally:
        close_seg()


# ---------------------------------------------------------------- transcription par morceaux
def run_deep_filter_file(wav: Path, workdir: str):
    out_dir = os.path.join(workdir, "out")
    proc = subprocess.Popen([DF_BIN, "-o", out_dir, str(wav)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    while proc.poll() is None:
        if JOB["cancel"]:
            proc.kill()
            proc.wait()
            return None
        time.sleep(0.3)
    if proc.returncode != 0:
        raise RuntimeError("la réduction de bruit a échoué")
    return os.path.join(out_dir, wav.name)


def transcribe_audio(audio_id: str):
    """Transcrit un audio complet. Renvoie None si la transcription est annulée."""
    wav, _ = audio_paths(audio_id)
    set_current(audio_id, 0.0, "loading")
    fw = get_fw()
    workdir = None
    try:
        src = str(wav)
        if SETTINGS["denoise"] and DF_AVAILABLE:
            set_current(audio_id, None, "denoise")
            workdir = tempfile.mkdtemp()
            src = run_deep_filter_file(wav, workdir)
            if src is None:
                return None
        set_current(audio_id, 0.0, "transcribe")
        segments, info = fw.transcribe(
            src,
            language=None if LANG == "auto" else LANG,
            vad_filter=True,
            word_timestamps=True,
            beam_size=BEAM_CHUNKS,
        )
        duration = max(float(info.duration), 0.001)
        texts, words, segs = [], [], []
        for seg in segments:
            if JOB["cancel"]:
                return None
            text = seg.text.strip()
            texts.append(text)
            segs.append({"start": round(seg.start, 2), "end": round(seg.end, 2), "text": text})
            for w in (seg.words or []):
                words.append({"word": w.word.strip(), "start": round(w.start, 2), "end": round(w.end, 2)})
            set_progress(min(seg.end / duration, 1.0))
        if JOB["cancel"]:
            return None
        return {"text": " ".join(t for t in texts if t), "words": words, "segments": segs, "duration": round(duration, 1)}
    finally:
        if workdir:
            shutil.rmtree(workdir, ignore_errors=True)


def commit_transcription(audio_id: str, res: dict):
    """N'écrit dans le fichier de la session qu'une fois l'audio entièrement transcrit."""
    session = JOB["session"]
    txt, jf = TRANS_DIR / f"{session}.txt", TRANS_DIR / f"{session}.json"
    if res["text"]:
        with open(txt, "a", encoding="utf-8") as f:
            f.write(res["text"] + "\n\n")
    data = read_json(jf, {"name": session, "created": datetime.now().isoformat(), "items": []})
    data["items"].append({
        "audio_id": audio_id,
        "created": id_to_iso(audio_id),
        "duration": res["duration"],
        "text": res["text"],
        "words": res["words"],
        "segments": res["segments"],
        "transcribed_at": datetime.now().isoformat(),
    })
    write_json(jf, data)
    write_json(audio_paths(audio_id)[1], {"transcribed": True, "session": session})


def job_loop():
    try:
        while not JOB["cancel"]:
            audio_id = next_pending()
            if audio_id is None:  # tout est transcrit : la session se termine d'elle-même
                break
            try:
                res = transcribe_audio(audio_id)
            except Exception as exc:
                traceback.print_exc()
                JOB["failed"][audio_id] = str(exc) or "erreur de transcription"
                set_current(None, 0, "")
                continue
            if res is None:  # annulé : rien n'est écrit, l'audio reste à transcrire
                break
            commit_transcription(audio_id, res)
            set_current(None, 0, "")
    finally:
        with JOB_LOCK:
            JOB.update(active=False, cancel=False, current=None, last_session=JOB["session"])


@app.get("/api/state")
def api_state():
    return {"audios": list_audios(), "job": job_state(), "settings": dict(SETTINGS)}


@app.post("/api/settings")
async def api_settings(request: Request):
    try:
        cfg = await request.json()
    except ValueError:
        cfg = {}
    if "denoise" in cfg:
        SETTINGS["denoise"] = bool(cfg["denoise"]) and DF_AVAILABLE
    return dict(SETTINGS)


@app.post("/api/transcribe/start")
def api_transcribe_start():
    with JOB_LOCK:
        if JOB["active"]:
            return {"ok": True, "already": True}
        if next_pending(include_failed=True) is None:
            return {"ok": False, "reason": "aucun audio à transcrire"}
        TRANS_DIR.mkdir(parents=True, exist_ok=True)
        name = new_stamp("session_", TRANS_DIR, (".txt", ".json"))
        (TRANS_DIR / f"{name}.txt").touch()
        write_json(TRANS_DIR / f"{name}.json", {"name": name, "created": datetime.now().isoformat(), "items": []})
        JOB.update(active=True, cancel=False, session=name, current=None, failed={})
    threading.Thread(target=job_loop, daemon=True).start()
    return {"ok": True, "session": name}


@app.post("/api/transcribe/cancel")
def api_transcribe_cancel():
    with JOB_LOCK:
        if JOB["active"]:
            JOB["cancel"] = True
    return {"ok": True}


@app.delete("/api/audios/{audio_id}")
def api_delete_audio(audio_id: str):
    check_id(audio_id)
    cur = job_state()["current"]
    if cur and cur["id"] == audio_id:
        raise HTTPException(status_code=409, detail="cet audio est en cours de transcription")
    wav, meta = audio_paths(audio_id)
    wav.unlink(missing_ok=True)
    meta.unlink(missing_ok=True)
    return {"ok": True}


@app.post("/api/audios/{audio_id}/restore")
def api_restore_audio(audio_id: str):
    check_id(audio_id)
    wav, meta = audio_paths(audio_id)
    if not wav.exists():
        raise HTTPException(status_code=404, detail="audio introuvable")
    write_json(meta, {"transcribed": False, "session": None})
    return {"ok": True}


@app.get("/audio/{audio_id}.wav")
def api_audio_file(audio_id: str):
    check_id(audio_id)
    wav, _ = audio_paths(audio_id)
    if not wav.exists():
        raise HTTPException(status_code=404, detail="audio introuvable")
    return FileResponse(wav, media_type="audio/wav")


# ---------------------------------------------------------------- consultation des transcriptions
@app.get("/api/sessions")
def api_sessions():
    out = []
    for jf in sorted(TRANS_DIR.glob("session_*.json"), reverse=True):
        data = read_json(jf, None)
        if not data:
            continue
        items = data.get("items", [])
        out.append({
            "name": jf.stem,
            "created": data.get("created"),
            "count": len(items),
            "words": sum(len(i.get("words", [])) for i in items),
        })
    return out


@app.get("/api/sessions/{name}")
def api_session(name: str):
    check_id(name)
    data = read_json(TRANS_DIR / f"{name}.json", None)
    if data is None:
        raise HTTPException(status_code=404, detail="session introuvable")
    for item in data.get("items", []):
        item["audio_exists"] = audio_paths(item["audio_id"])[0].exists()
    return data


# ================================================================ MODE LIVE : routes
async def wlk_reachable() -> bool:
    url = urlparse(WLK_URL)
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(url.hostname, url.port or 80), 0.8)
        writer.close()
        return True
    except Exception:
        return False


@app.get("/api/engines")
async def api_engines():
    wlk_ok = await wlk_reachable()
    return {
        "deepfilter": DF_AVAILABLE,
        "engines": [
            {
                "id": "whisper", "name": "Whisper (faster-whisper)", "available": True, "supports_denoise": True,
                "note": "Transcrit phrase par phrase, après chaque pause : précis, mais le texte arrive par à-coups.",
            },
            {
                "id": "sherpa", "name": sherpa_name(), "available": sherpa_rec is not None, "supports_denoise": False,
                "note": "Vrai streaming : le texte s'écrit en continu pendant que tu parles. Modèle léger, moins précis que Whisper."
                        + (" Le modèle Kroko est sous licence non commerciale." if "kroko" in (SHERPA_MODEL or "kroko").lower() else ""),
                "hint": "Le modèle de streaming est introuvable : réinstalle CorTranscript ou reconstruis son image Docker.",
            },
            {
                "id": "whisperlivekit", "name": "WhisperLiveKit", "available": wlk_ok, "supports_denoise": False,
                "note": "Whisper en pseudo-streaming (fenêtres glissantes) : les mots se figent avec quelques secondes de retard.",
                "hint": "WhisperLiveKit n'est pas encore prêt (il charge son modèle au démarrage) : patiente un moment ou consulte les journaux de CorTranscript.",
            },
        ],
    }


@app.websocket("/ws")
async def ws_live(ws: WebSocket):
    await ws.accept()
    handler = LIVE_HANDLERS.get(ws.query_params.get("engine", "whisper"))
    if handler is None:
        await ws.send_json({"type": "error", "text": "moteur inconnu"})
        await ws.close()
        return
    TRANS_DIR.mkdir(parents=True, exist_ok=True)
    name = new_stamp("transcription_", TRANS_DIR, (".txt",))
    path = TRANS_DIR / f"{name}.txt"
    path.touch()
    doc = LiveDoc(path)
    LIVE_DOCS[name] = doc
    while len(LIVE_DOCS) > 50:
        LIVE_DOCS.popitem(last=False)
    await ws.send_json({"type": "info", "available": DF_AVAILABLE, "file": name})
    await handler(DocSocket(ws), doc)


@app.post("/api/live/edit")
async def api_live_edit(request: Request):
    """Enregistre dans le fichier texte les corrections faites dans l'éditeur de la page « Live »."""
    try:
        cfg = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="requête invalide")
    if not isinstance(cfg, dict):
        raise HTTPException(status_code=400, detail="requête invalide")
    doc = LIVE_DOCS.get(str(cfg.get("file", "")))
    if doc is None:
        raise HTTPException(status_code=404, detail="session inconnue (le serveur a redémarré ?)")
    text, upto = cfg.get("text"), cfg.get("upto", 0)
    if not isinstance(text, str) or not isinstance(upto, int):
        raise HTTPException(status_code=400, detail="requête invalide")
    try:
        doc.apply_edit(text, upto)
    except OSError:
        raise HTTPException(status_code=500, detail="écriture impossible")
    return {"ok": True}


@app.post("/denoise")
async def denoise_endpoint(request: Request):
    if not DF_AVAILABLE:
        return Response("DeepFilterNet indisponible", status_code=503)
    data = await request.body()
    if not data or len(data) > 20_000_000:
        return Response("Audio invalide", status_code=400)
    try:
        out = await asyncio.get_running_loop().run_in_executor(executor, denoise_wav, data)
    except Exception:
        traceback.print_exc()
        return Response("Échec du traitement", status_code=500)
    return Response(out, media_type="audio/wav")


@app.get("/api/health")
async def health():
    return {"application": "CorTranscript", "status": "ready"}


@app.get("/")
async def index():
    return FileResponse(APP_DIR / "index.html")
