"""Transport and persistence regressions without downloading speech models."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import Mock, patch

READY = all(importlib.util.find_spec(name) for name in ('fastapi', 'numpy', 'httpx'))


@unittest.skipUnless(READY, 'Install runtime dependencies and httpx to run backend tests')
class BackendTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        env = patch.dict(os.environ, {
            'AUDIO_DIR': str(self.root / 'audio'), 'TRANSCRIPTIONS_DIR': str(self.root / 'texts'),
            'SHERPA_MODEL_DIR': str(self.root / 'no-model'), 'DEEPFILTER_BIN': str(self.root / 'no-filter'),
        })
        env.start()
        self.addCleanup(env.stop)
        # No actual speech weights are used in these transport tests.
        previous_sherpa = sys.modules.get('sherpa_onnx')
        sys.modules['sherpa_onnx'] = types.ModuleType('sherpa_onnx')
        def restore_sherpa():
            if previous_sherpa is None:
                sys.modules.pop('sherpa_onnx', None)
            else:
                sys.modules['sherpa_onnx'] = previous_sherpa
        self.addCleanup(restore_sherpa)
        spec = importlib.util.spec_from_file_location('test_cortranscript_backend', Path(__file__).resolve().parents[1] / 'app.py')
        self.app = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.app)
        from fastapi.testclient import TestClient
        self.client = self.enterContext(TestClient(self.app.app))
        self.addCleanup(self.app.executor.shutdown)
        self.addCleanup(self.app.sherpa_executor.shutdown)

    def test_live_uses_kroko_without_loading_whisper_and_saves_edits(self):
        class Stream:
            reset = False
            def accept_waveform(self, rate, samples):
                self.samples = samples
            def input_finished(self):
                pass
        class Kroko:
            def create_stream(self):
                return Stream()
            def is_ready(self, stream):
                return False
            def get_result(self, stream):
                return '' if stream.reset else 'Bonjour'
            def is_endpoint(self, stream):
                return True
            def reset(self, stream):
                stream.reset = True
        self.app.sherpa_rec = Kroko()
        self.assertEqual([e['id'] for e in self.client.get('/api/engines').json()['engines']], ['sherpa'])
        with self.client.websocket_connect('/ws') as ws:
            session = ws.receive_json()['file']
            ws.send_bytes(b'\x01\x00' * 16000)
            self.assertEqual(ws.receive_json(), {'type': 'final', 'text': 'Bonjour', 'n': 1})
            ws.receive_json()  # clear partial text after the endpoint
            ws.send_json({'stop': True})
        self.assertIsNone(self.app._fw)
        self.assertEqual((self.app.TRANS_DIR / f'{session}.txt').read_text('utf-8'), 'Bonjour\n')
        result = self.client.post('/api/live/edit', json={'file': session, 'text': 'Bonjour corrigé', 'upto': 1})
        self.assertEqual(result.status_code, 200)
        self.assertEqual((self.app.TRANS_DIR / f'{session}.txt').read_text('utf-8'), 'Bonjour corrigé\n')

    def test_recording_chunks_still_use_whisper_and_save_word_timestamps(self):
        # Exercise recording boundaries, the real queue and persisted metadata.
        segment = types.SimpleNamespace(text=' Bonjour', start=0.0, end=0.5,
                                        words=[types.SimpleNamespace(word=' Bonjour', start=0.0, end=0.5)])
        whisper = Mock()
        whisper.transcribe.side_effect = lambda *a, **kw: (iter([segment]), types.SimpleNamespace(duration=1.0))
        constructor = Mock(return_value=whisper)
        faster = types.ModuleType('faster_whisper')
        faster.WhisperModel = constructor
        with patch.dict(sys.modules, {'faster_whisper': faster}):
            with self.client.websocket_connect('/ws/record') as ws:
                ws.send_bytes(b'\x01\x00' * 16000)
                ws.send_json({'cut': True})
                self.assertEqual(ws.receive_json()['type'], 'saved')
                ws.send_bytes(b'\x02\x00' * 16000)
                ws.send_json({'stop': True})
            self.assertIsNone(self.app._fw)
            response = self.client.post('/api/transcribe/start').json()
            self.assertTrue(response['ok'])
            deadline = time.monotonic() + 5
            while self.client.get('/api/state').json()['job']['active'] and time.monotonic() < deadline:
                time.sleep(0.01)
            data = self.client.get('/api/state').json()
            self.assertFalse(data['job']['active'])
            self.assertEqual(len(data['audios']), 2)
            self.assertTrue(all(audio['transcribed'] for audio in data['audios']))
            session = json.loads((self.app.TRANS_DIR / (response['session'] + '.json')).read_text('utf-8'))
            self.assertEqual(len(session['items']), 2)
            self.assertEqual(session['items'][0]['words'], [{'word': 'Bonjour', 'start': 0.0, 'end': 0.5}])
            constructor.assert_called_once()
            self.assertEqual(whisper.transcribe.call_args.kwargs['beam_size'], 5)
            self.assertTrue(whisper.transcribe.call_args.kwargs['vad_filter'])
            self.assertTrue(whisper.transcribe.call_args.kwargs['word_timestamps'])

    def test_mixer_script_is_served(self):
        result = self.client.get('/audio-inputs.js')
        self.assertEqual(result.status_code, 200)
        self.assertIn('javascript', result.headers['content-type'])
        self.assertIn('captureMixedAudio', result.text)


if __name__ == '__main__':
    unittest.main()
