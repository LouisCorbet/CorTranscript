"""Small desktop launcher, frozen independently of the machine-learning runtime."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import webbrowser


def bundle_directory():
    return Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent.parent / 'build' / 'windows' / 'CorTranscript'


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def read_status(url):
    # A configured company proxy must never receive local audio/API requests.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=2) as response:
        return json.load(response)


def runtime_environment(bundle, data):
    env = os.environ.copy()
    # Ignore the build machine's or user's Python/ML configuration.
    for key in ('PYTHONHOME', 'PYTHONPATH', 'HF_TOKEN', 'HUGGING_FACE_HUB_TOKEN'):
        env.pop(key, None)
    for name in ('audio', 'transcriptions', 'logs', 'cache'):
        (data / name).mkdir(parents=True, exist_ok=True)
    env.update({
        'CORTRANSCRIPT_DESKTOP': '1',
        'WHISPER_MODEL': str(bundle / 'models' / 'whisper'),
        'WHISPER_LANGUAGE': 'fr', 'WHISPER_DEVICE': 'cpu',
        'CUDA_VISIBLE_DEVICES': '-1',
        'WHISPER_COMPUTE_TYPE': 'int8', 'WHISPER_BEAM_CHUNKS': '5',
        'AUDIO_DIR': str(data / 'audio'), 'TRANSCRIPTIONS_DIR': str(data / 'transcriptions'),
        'SHERPA_MODEL_DIR': str(bundle / 'models' / 'sherpa'),
        'DEEPFILTER_BIN': str(bundle / 'bin' / 'deep-filter.exe'),
        'HF_HOME': str(data / 'cache' / 'huggingface'),
        'HF_HUB_OFFLINE': '1',
        'HF_HUB_DISABLE_TELEMETRY': '1', 'PYTHONUNBUFFERED': '1',
        'PYTHONIOENCODING': 'utf-8',
    })
    return env


class Services:
    def __init__(self, bundle, data):
        self.bundle, self.data = bundle, data
        self.processes, self.logs = [], []
        self.url = None

    def start(self):
        # PyInstaller changes the DLL search path for its own runtime. External
        # embedded Python must resolve DLLs from its own directory instead.
        if sys.platform == 'win32' and getattr(sys, 'frozen', False):
            import ctypes
            ctypes.windll.kernel32.SetDllDirectoryW(None)
        env = runtime_environment(self.bundle, self.data)
        app_port = free_port()
        self.url = f'http://127.0.0.1:{app_port}'
        log = (self.data / 'logs' / 'app.log').open('w', encoding='utf-8')
        self.logs.append(log)
        self.processes.append(subprocess.Popen(
            [str(self.bundle / 'runtime' / 'python.exe'),
             str(self.bundle / 'app' / 'windows_server.py'), '--port', str(app_port)],
            cwd=self.bundle / 'app', env=env, stdout=log, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)))

    def ready(self):
        for process in self.processes:
            if process.poll() is not None:
                raise RuntimeError('Un moteur s’est arrêté. Consulte les journaux pour connaître la cause.')
        try:
            return read_status(self.url + '/api/health').get('application') == 'CorTranscript'
        except (OSError, ValueError):
            return False

    def stop(self):
        for process in reversed(self.processes):
            if process.poll() is None:
                # Includes child processes if an audio treatment is in progress.
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), timeout=20)
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=20)
        for log in self.logs:
            log.close()
        self.processes.clear()
        self.logs.clear()


def smoke_test(bundle):
    # An isolated, writable data directory: never package the developer's recordings.
    with tempfile.TemporaryDirectory(prefix='CorTranscript-check-') as temporary:
        services = Services(bundle, Path(temporary))
        try:
            services.start()
            deadline = time.monotonic() + 600
            while not services.ready():
                if time.monotonic() > deadline:
                    raise TimeoutError('Packaged engines did not become ready within 10 minutes')
                time.sleep(1)
            engines = read_status(services.url + '/api/engines')
            if (not engines['deepfilter'] or [e['id'] for e in engines['engines']] != ['sherpa']
                    or not all(e['available'] for e in engines['engines'])):
                raise RuntimeError(f'Packaged engine unavailable: {engines}')
            # Test binary execution and WAV round-trip, not just the existence of an .exe.
            import io
            import wave
            audio = io.BytesIO()
            with wave.open(audio, 'wb') as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(16000)
                wav.writeframes(b'\x00\x00' * 16000)
            request = urllib.request.Request(services.url + '/denoise', data=audio.getvalue(),
                                             headers={'Content-Type': 'audio/wav'})
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(request, timeout=120) as response:
                with wave.open(io.BytesIO(response.read())) as result:
                    assert result.getnframes() > 0
            # Verify the lazy Whisper path using an actual recorded-format WAV.
            audio_id = '2000-01-01_00-00-00'
            (services.data / 'audio' / (audio_id + '.wav')).write_bytes(audio.getvalue())
            request = urllib.request.Request(services.url + '/api/transcribe/start', data=b'{}',
                                             headers={'Content-Type': 'application/json'})
            with opener.open(request, timeout=10) as response:
                assert json.load(response)['ok']
            deadline = time.monotonic() + 180
            while True:
                state = read_status(services.url + '/api/state')
                if not state['job']['active']:
                    break
                if time.monotonic() > deadline:
                    raise TimeoutError('Packaged Whisper chunk transcription timed out')
                time.sleep(0.25)
            if not any(item['id'] == audio_id and item['transcribed'] for item in state['audios']):
                raise RuntimeError(f'Packaged chunk transcription failed: {state}')
            print('CorTranscript packaged runtime: Kroko, Whisper chunks and denoising ready.', flush=True)
        except Exception:
            for path in (Path(temporary) / 'logs').glob('*.log'):
                print(path.name, path.read_text('utf-8', errors='replace')[-20000:], flush=True)
            raise
        finally:
            services.stop()


def main():
    bundle = bundle_directory()
    if '--smoke-test' in sys.argv:
        import contextlib
        import traceback
        log_path = Path(tempfile.gettempdir()) / 'CorTranscript-smoke.log'
        with log_path.open('w', encoding='utf-8') as log:
            with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                try:
                    smoke_test(bundle)
                except Exception:
                    traceback.print_exc()
                    raise
        return
    import msvcrt
    import tkinter as tk
    from tkinter import messagebox
    data = Path(os.environ['LOCALAPPDATA']) / 'CorTranscript'
    data.mkdir(parents=True, exist_ok=True)
    # Windows releases this lock even after a crash. A second shortcut click
    # reopens the running instance instead of loading all models a second time.
    lock = (data / 'instance.lock').open('a+b')
    lock.seek(0)
    if not lock.read(1):
        lock.write(b'0')
        lock.flush()
    lock.seek(0)
    try:
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        try:
            url = (data / 'instance.url').read_text('utf-8')
            if read_status(url + '/api/health').get('application') == 'CorTranscript':
                webbrowser.open(url)
                return
        except (OSError, ValueError):
            pass
        messagebox.showinfo('CorTranscript', 'CorTranscript est déjà ouvert ou en cours de démarrage.')
        return
    root = tk.Tk()
    root.title('CorTranscript')
    root.geometry('520x210')
    root.resizable(False, False)
    status = tk.StringVar(value='Chargement de Kroko…')
    tk.Label(root, text='CorTranscript', font=('Segoe UI', 20, 'bold')).pack(pady=(20, 12))
    tk.Label(root, textvariable=status, wraplength=480).pack(pady=5)
    services = Services(bundle, data)
    open_button = tk.Button(root, text='Ouvrir CorTranscript', state='disabled', command=lambda: webbrowser.open(services.url))
    open_button.pack(pady=8)
    tk.Button(root, text='Ouvrir les journaux', command=lambda: os.startfile(data / 'logs')).pack()
    started = time.monotonic()
    opened = False
    failed = False

    def close():
        if opened and not messagebox.askokcancel('CorTranscript', 'Arrêter CorTranscript ? Termine tes enregistrements avant de fermer.'):
            return
        try:
            services.stop()
        finally:
            (data / 'instance.url').unlink(missing_ok=True)
            root.destroy()

    def poll():
        nonlocal opened, failed
        if failed:
            return
        try:
            if services.ready():
                if not opened:
                    opened = True
                    (data / 'instance.url').write_text(services.url, 'utf-8')
                    status.set('Prêt. Garde cette fenêtre ouverte pendant l’utilisation.')
                    open_button.config(state='normal')
                    webbrowser.open(services.url)
            elif time.monotonic() - started > 600:
                raise TimeoutError('Le démarrage prend trop de temps. Consulte les journaux puis relance CorTranscript.')
        except Exception as exc:
            failed = True
            status.set('Échec du démarrage. Les détails sont dans les journaux.')
            messagebox.showerror('CorTranscript', str(exc))
            services.stop()
            return
        root.after(1000, poll)

    root.protocol('WM_DELETE_WINDOW', close)
    try:
        services.start()
        root.after(500, poll)
        root.mainloop()
    finally:
        services.stop()
        lock.close()


if __name__ == '__main__':
    main()
