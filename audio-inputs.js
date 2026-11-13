/* Shared audio capture for live, chunk recording and the denoising comparison. */
(function (root) {
  "use strict";

  async function captureMixedAudio({ microphoneIds = [], systemAudio = false, signal, onSourcesChanged = () => {} }) {
    if (!microphoneIds.length && !systemAudio) throw new Error("Sélectionne au moins une entrée audio.");
    if (signal?.aborted) throw new DOMException("Capture annulée.", "AbortError");
    const entries = [];
    let context, output, mix, limiter, closed = false;
    const notify = (ended = null) => onSourcesChanged({
      labels: entries.filter(e => !e.ended).map(e => e.label), ended,
    });
    const stop = () => {
      if (closed) return;
      closed = true;
      signal?.removeEventListener("abort", stop);
      for (const entry of entries) {
        for (const track of entry.stream.getTracks()) {
          track.removeEventListener("ended", entry.onEnded);
          track.stop();
        }
        entry.node?.disconnect();
      }
      output?.stream.getTracks().forEach(track => track.stop());
      context?.close().catch(() => {});
      onSourcesChanged(null);
    };
    signal?.addEventListener("abort", stop, { once: true });
    const add = (stream, label) => {
      if (closed) {
        stream.getTracks().forEach(track => track.stop());
        throw new DOMException("Capture annulée.", "AbortError");
      }
      // Keep the display video track alive for the browser's sharing indicator,
      // but only connect the audio to the mixer. No video is sent to the server.
      const entry = { stream, label, ended: false, node: null, onEnded: null };
      entries.push(entry);
      if (!stream.getAudioTracks().some(t => t.readyState === "live")) {
        throw new Error("Aucun son partagé : coche « Partager l’audio » dans la fenêtre du navigateur.");
      }
      return entry;
    };
    try {
      // Request screen sharing before any awaited microphone operation: browsers
      // require getDisplayMedia to originate from the user's button click.
      if (systemAudio) {
        if (!navigator.mediaDevices.getDisplayMedia) throw new Error("Le partage du son n’est pas disponible dans ce navigateur.");
        const shared = await navigator.mediaDevices.getDisplayMedia({
          video: true, audio: true, systemAudio: "include",
        });
        add(shared, "Visio / son de l’ordinateur");
      }
      const devices = new Set();
      for (const id of new Set(microphoneIds)) {
        if (closed) throw new DOMException("Capture annulée.", "AbortError");
        const stream = await navigator.mediaDevices.getUserMedia({ audio: {
          deviceId: id && id !== "default" ? { exact: id } : undefined,
          channelCount: 1, echoCancellation: systemAudio,
          noiseSuppression: false, autoGainControl: true,
        } });
        const track = stream.getAudioTracks()[0];
        const resolved = track?.getSettings().deviceId;
        // The default and named device can refer to the same physical input.
        if (resolved && devices.has(resolved)) { stream.getTracks().forEach(t => t.stop()); continue; }
        if (resolved) devices.add(resolved);
        add(stream, track?.label || "Micro");
      }
      context = new AudioContext({ sampleRate: 16000 });
      output = context.createMediaStreamDestination();
      output.channelCount = 1;
      output.channelCountMode = "explicit";
      mix = context.createGain();
      mix.channelCount = 1;
      mix.channelCountMode = "explicit";
      // Sum every input. Headroom and a compressor reduce overload when several
      // people speak at once; the recording worklet finally bounds PCM samples.
      mix.gain.value = 1 / Math.sqrt(entries.length);
      limiter = context.createDynamicsCompressor();
      limiter.threshold.value = -3;
      limiter.knee.value = 0;
      limiter.ratio.value = 20;
      limiter.attack.value = 0.003;
      limiter.release.value = 0.1;
      mix.connect(limiter).connect(output);
      for (const entry of entries) {
        entry.node = context.createMediaStreamSource(new MediaStream(entry.stream.getAudioTracks()));
        entry.node.connect(mix);
        entry.onEnded = () => {
          if (closed || entry.ended) return;
          entry.ended = true;
          entry.node.disconnect();
          entry.stream.getTracks().forEach(t => t.stop());
          const remaining = entries.filter(e => !e.ended).length;
          mix.gain.value = remaining ? 1 / Math.sqrt(remaining) : 1;
          notify(entry.label);
          if (!remaining) {
            output.stream.getAudioTracks()[0].dispatchEvent(new Event("ended"));
            stop();
          }
        };
        entry.stream.getTracks().forEach(t => t.addEventListener("ended", entry.onEnded, { once: true }));
        if (entry.stream.getAudioTracks().every(t => t.readyState === "ended")) entry.onEnded();
      }
      if (closed) throw new Error("Les entrées audio ont été déconnectées.");
      await context.resume();
      if (closed) throw new DOMException("Capture annulée.", "AbortError");
      notify();
      const stream = output.stream;
      stream.release = stop;
      return stream;
    } catch (error) {
      stop();
      throw error;
    }
  }

  function releaseAudio(stream) {
    if (stream?.release) stream.release();
    else stream?.getTracks().forEach(track => track.stop());
  }
  root.CorAudio = { captureMixedAudio, releaseAudio };
})(globalThis);
