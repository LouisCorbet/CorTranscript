"""Real browser audio graph tests with generated inputs, requiring no microphones."""
import http.server
import importlib.util
import json
import os
from pathlib import Path
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
MOCK_MEDIA = r'''
window.createdInputs = [];
window.mediaRequests = [];
window.failMicrophone = null;
function tone(id) {
  const context = new AudioContext({sampleRate: 48000});
  const oscillator = context.createOscillator();
  oscillator.frequency.value = {a: 440, b: 880, display: 1320}[id];
  const gain = context.createGain(); gain.gain.value = 0.1;
  const output = context.createMediaStreamDestination();
  oscillator.connect(gain).connect(output); oscillator.start(); context.resume();
  const stream = output.stream;
  const track = stream.getAudioTracks()[0];
  Object.defineProperty(track, 'label', {value: id === 'display' ? 'Visio' : 'Micro ' + id});
  const settings = track.getSettings.bind(track);
  track.getSettings = () => ({...settings(), deviceId: id});
  const stop = track.stop.bind(track);
  track.stop = () => { stop(); if (context.state !== "closed") context.close().catch(() => {}); };
  createdInputs.push({id, stream});
  return stream;
}
Object.defineProperties(navigator.mediaDevices, {
  enumerateDevices: {value: async () => ['a','b'].map(id => ({kind:'audioinput',deviceId:id,label:'Micro '+id}))},
  getDisplayMedia: {value: async () => {
    mediaRequests.push('display');
    const stream = tone('display');
    if (window.noSharedAudio) {
      const canvas = document.createElement('canvas');
      canvas.width = canvas.height = 8;
      canvas.getContext('2d').fillRect(0,0,8,8);
      const video = canvas.captureStream().getVideoTracks()[0];
      stream.getAudioTracks().forEach(track => { track.stop(); stream.removeTrack(track); });
      stream.addTrack(video);
    }
    return stream;
  }},
  getUserMedia: {value: async options => {
    const id = options.audio?.deviceId?.exact || 'a';
    mediaRequests.push(id);
    if (id === window.failMicrophone) throw new DOMException('Micro refusé', 'NotAllowedError');
    if (window.deferMicrophone) await new Promise(resolve => {window.resolveMicrophone = resolve;});
    return tone(id);
  }}
});
window.sentPcm = 0;
window.WebSocket = class {
  constructor(url) {
    this.url = url; this.readyState = 0;
    setTimeout(() => {
      this.readyState = 1; this.onopen?.();
      if (!url.includes('/ws/record')) this.onmessage?.({data:JSON.stringify({type:'info',file:'test',available:true})});
    }, 10);
  }
  send(data) {
    if (typeof data !== 'string') sentPcm += data.byteLength;
    else if (JSON.parse(data).stop) setTimeout(() => this.close(), 20);
  }
  close() { if (this.readyState === 3) return; this.readyState = 3; this.onclose?.(); }
};
'''


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass
    def do_GET(self):
        route = self.path.split('?')[0]
        if route == '/api/engines':
            data = {'deepfilter': True, 'engines': [{'id':'sherpa','available':True,'note':'Kroko FR','supports_denoise':False}]}
        elif route == '/api/state':
            data = {'audios': [], 'job': {'active':False,'current':None,'session':None,'last_session':None}, 'settings':{'denoise':False}}
        elif route == '/api/sessions':
            data = []
        else:
            file = ROOT / ('index.html' if route == '/' else route.lstrip('/'))
            if not file.is_file() or not file.resolve().is_relative_to(ROOT):
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header('Content-Type','application/javascript' if file.suffix == '.js' else 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(file.read_bytes())
            return
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())


@unittest.skipUnless(importlib.util.find_spec('playwright'), 'Install playwright and Chromium for browser tests')
class AudioBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.driver = sync_playwright().start()
        binary = os.environ.get('CHROMIUM_BINARY')
        cls.browser = cls.driver.chromium.launch(headless=True, executable_path=binary,
            args=['--no-sandbox', '--autoplay-policy=no-user-gesture-required'])
        cls.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.worker = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.worker.start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}'
    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.driver.stop()
        cls.server.shutdown()
        cls.server.server_close()
        cls.worker.join()
    def setUp(self):
        self.page = self.browser.new_page()
        self.addCleanup(self.page.close)
        self.errors = []
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))
        self.page.add_init_script(MOCK_MEDIA)
        self.page.goto(self.url)
        self.page.wait_for_function('document.querySelectorAll("#devices input").length === 2 && !document.getElementById("btn").disabled')
    def tearDown(self):
        self.assertEqual(self.errors, [])

    def test_real_mixer_contains_every_source_and_continues_after_one_ends(self):
        result = self.page.evaluate('''async () => {
          const updates = [];
          const stream = await CorAudio.captureMixedAudio({microphoneIds:['a','b'],systemAudio:true,onSourcesChanged:s=>updates.push(s)});
          const context = new AudioContext({sampleRate:16000});
          const source = context.createMediaStreamSource(stream), analyser = context.createAnalyser();
          analyser.fftSize = 4096;
          analyser.smoothingTimeConstant = 0; // measure the current signal, not a smoothed history
          const mute = context.createGain(); mute.gain.value = 0;
          source.connect(analyser).connect(mute).connect(context.destination); await context.resume();
          const peaks = () => { const data = new Float32Array(analyser.frequencyBinCount); analyser.getFloatFrequencyData(data);
            return [440,880,1320].map(f => data[Math.round(f*analyser.fftSize/context.sampleRate)]); };
          await new Promise(r=>setTimeout(r,700)); const before = peaks();
          const track = createdInputs.find(x=>x.id==='display').stream.getAudioTracks()[0];
          track.stop(); track.dispatchEvent(new Event('ended'));
          await new Promise(r=>setTimeout(r,500)); const after = peaks();
          const liveAfterLoss = stream.getAudioTracks()[0].readyState;
          stream.release(); await context.close();
          return {before,after,liveAfterLoss,stopped:createdInputs.every(x=>x.stream.getTracks().every(t=>t.readyState==='ended')),
            notices:updates.filter(Boolean).map(s=>s.labels.length),order:mediaRequests};
        }''')
        self.assertTrue(all(value > -45 for value in result['before']), result)
        self.assertTrue(all(value > -45 for value in result['after'][:2]), result)
        self.assertLess(result['after'][2], -65, result)
        self.assertEqual(result['liveAfterLoss'], 'live')
        self.assertTrue(result['stopped'])
        self.assertEqual(result['notices'], [3, 2])
        self.assertEqual(result['order'], ['display','a','b'])

    def test_denied_second_microphone_releases_all_acquired_sources(self):
        result = self.page.evaluate('''async () => {
          failMicrophone='b';
          try { await CorAudio.captureMixedAudio({microphoneIds:['a','b'],systemAudio:true}); }
          catch(error) { return {error:error.name,stopped:createdInputs.every(x=>x.stream.getTracks().every(t=>t.readyState==='ended'))}; }
        }''')
        self.assertEqual(result, {'error':'NotAllowedError', 'stopped':True})

    def test_screen_share_without_audio_is_rejected_and_released(self):
        result = self.page.evaluate('''async () => {
          window.noSharedAudio=true;
          try { await CorAudio.captureMixedAudio({microphoneIds:['a'],systemAudio:true}); }
          catch(error) { return {message:error.message,stopped:createdInputs.every(x=>x.stream.getTracks().every(t=>t.readyState==='ended'))}; }
        }''')
        self.assertIn('Aucun son partagé', result['message'])
        self.assertTrue(result['stopped'])

    def test_abort_releases_sources_even_when_microphone_permission_finishes_late(self):
        result = self.page.evaluate('''async () => {
          const controller = new AbortController(); window.deferMicrophone=true;
          const capture = CorAudio.captureMixedAudio({microphoneIds:['a'],systemAudio:true,signal:controller.signal});
          while(!window.resolveMicrophone) await new Promise(r=>setTimeout(r,10));
          controller.abort(); resolveMicrophone();
          try {await capture;} catch(error) {return {name:error.name,stopped:createdInputs.every(x=>x.stream.getTracks().every(t=>t.readyState==='ended'))};}
        }''')
        self.assertEqual(result, {'name':'AbortError','stopped':True})

    def test_live_and_chunks_send_the_mixed_audio_and_release_devices_on_stop(self):
        self.page.check('#devices input[value="b"]')
        self.page.check('#systemAudio')
        self.assertEqual(self.page.locator('#engine').count(), 0)
        self.assertFalse(self.page.locator('#processingCard').is_visible())
        self.page.click('#btn')
        self.page.wait_for_function('sentPcm > 0')
        self.assertIn('Micro a', self.page.locator('#captureStatus').inner_text())
        self.assertIn('Micro b', self.page.locator('#captureStatus').inner_text())
        self.assertIn('ordinateur', self.page.locator('#captureStatus').inner_text())
        self.page.click('#btn')
        self.page.wait_for_function('createdInputs.every(x=>x.stream.getTracks().every(t=>t.readyState==="ended"))')
        self.page.click('[data-page="chunks"]')
        self.assertTrue(self.page.locator('#processingCard').is_visible())
        before = self.page.evaluate('sentPcm')
        self.page.click('#recBtn')
        self.page.wait_for_function('(before)=>sentPcm > before', arg=before)
        self.page.click('#recBtn')
        self.page.wait_for_function('createdInputs.every(x=>x.stream.getTracks().every(t=>t.readyState==="ended"))')
        self.assertEqual(self.page.locator('#captureStatus').inner_text(), '')


if __name__ == '__main__':
    unittest.main()
