"""Download model assets at build time, then validate the actual packaged runtime."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tarfile
import urllib.request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--model', default='small')
    args = parser.parse_args()
    bundle = args.bundle.resolve()
    models = bundle / 'models'
    models.mkdir(parents=True, exist_ok=True)
    os.environ['HF_HOME'] = str(models / 'huggingface')
    os.environ['HF_HUB_DISABLE_SYMLINKS_WARNING'] = '1'
    from faster_whisper.utils import download_model
    model_dir = models / 'whisper'
    download_model(args.model, output_dir=str(model_dir))
    from faster_whisper import WhisperModel
    import numpy as np
    model = WhisperModel(str(model_dir), device='cpu', compute_type='int8')
    # Exercise the same VAD and decoder API as the chunk transcription path.
    segments, _ = model.transcribe(np.zeros(16000, dtype=np.float32),
                                  language='fr', vad_filter=True, word_timestamps=True, beam_size=5)
    list(segments)
    sherpa_name = 'sherpa-onnx-streaming-zipformer-fr-kroko-2025-08-06'
    archive = models / 'sherpa.tar.bz2'
    urllib.request.urlretrieve(
        f'https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/{sherpa_name}.tar.bz2', archive)
    target = models / 'sherpa'
    target.mkdir(exist_ok=True)
    with tarfile.open(archive) as tar:
        # Only regular files below the archive's root; never extract links or
        # paths outside the staging area.
        for member in tar.getmembers():
            parts = Path(member.name).parts
            if not member.isfile() or len(parts) < 2:
                continue
            relative = Path(*parts[1:])
            destination = (target / relative).resolve()
            if not destination.is_relative_to(target.resolve()):
                raise ValueError('Unsafe model archive path')
            destination.parent.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(member) as src, destination.open('wb') as dst:
                import shutil
                shutil.copyfileobj(src, dst)
    archive.unlink()
    (bundle / 'config.json').write_text(json.dumps({'model': args.model, 'sherpa_model': sherpa_name}), 'utf-8')
    subprocess.run([str(bundle / 'bin' / 'deep-filter.exe'), '--help'], check=True)


if __name__ == '__main__':
    main()
