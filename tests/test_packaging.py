import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('launcher', Path(__file__).resolve().parents[1] / 'packaging' / 'launcher.py')
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class PackagingTests(unittest.TestCase):
    def test_relocated_bundle_uses_private_models_and_user_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary) / 'Bureau de Louis' / 'CorTranscript installé'
            bundle.mkdir(parents=True)
            (bundle / 'config.json').write_text(json.dumps({'sherpa_model': 'French-model'}))
            cache = bundle / 'models' / 'torch'
            cache.mkdir(parents=True)
            (cache / 'model.jit').write_bytes(b'test')
            data = Path(temporary) / 'Profil élève' / 'CorTranscript'
            with patch.dict(os.environ, {'PYTHONPATH': '/wrong', 'PYTHONHOME': '/wrong', 'WHISPER_DEVICE': 'cuda', 'HF_TOKEN': 'do-not-package'}):
                env = launcher.runtime_environment(bundle, data)
            self.assertEqual(env['WHISPER_DEVICE'], 'cpu')
            self.assertEqual(env['WHISPER_MODEL'], str(bundle / 'models' / 'whisper'))
            self.assertEqual(env['AUDIO_DIR'], str(data / 'audio'))
            self.assertNotIn('PYTHONHOME', env)
            self.assertNotIn('PYTHONPATH', env)
            self.assertNotIn('HF_TOKEN', env)
            self.assertEqual((data / 'cache' / 'torch' / 'model.jit').read_bytes(), b'test')
            # Existing user cache is retained on the next launch.
            (data / 'cache' / 'torch' / 'model.jit').write_bytes(b'user cache')
            launcher.runtime_environment(bundle, data)
            self.assertEqual((data / 'cache' / 'torch' / 'model.jit').read_bytes(), b'user cache')

    def test_status_request_never_uses_environment_proxy(self):
        import http.server
        import threading
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"application": "CorTranscript"}')
            def log_message(self, *args):
                pass
        with http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server:
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                with patch.dict(os.environ, {'http_proxy': 'http://127.0.0.1:1', 'no_proxy': ''}):
                    self.assertEqual(launcher.read_status(f'http://127.0.0.1:{server.server_port}')['application'], 'CorTranscript')
            finally:
                server.shutdown()
                worker.join()

    def test_child_failure_is_reported_before_readiness(self):
        from unittest.mock import Mock
        service = launcher.Services(Path('/bundle'), Path('/data'))
        process = Mock()
        process.poll.return_value = 1
        service.processes = [process]
        with self.assertRaisesRegex(RuntimeError, 'moteur'):
            service.ready()


if __name__ == '__main__':
    unittest.main()
