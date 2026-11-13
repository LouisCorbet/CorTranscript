# Composants tiers de CorTranscript

L'installateur contient Python, PyTorch, WhisperX, faster-whisper / CTranslate2,
WhisperLiveKit, sherpa-onnx, DeepFilterNet, FFmpeg et leurs dépendances.
Les mentions et licences des packages sont conservées dans leurs dossiers
`*.dist-info` sous `runtime/Lib/site-packages`, celles de Python dans `runtime`,
et la documentation de la distribution FFmpeg dans `licenses/ffmpeg-distribution`.
Le manifeste `build-manifest.json` indique les versions effectivement distribuées.

- Python : https://www.python.org/doc/copyright/
- PyTorch : https://github.com/pytorch/pytorch/blob/main/LICENSE
- WhisperX : https://github.com/m-bain/whisperX/blob/main/LICENSE
- faster-whisper : https://github.com/SYSTRAN/faster-whisper/blob/master/LICENSE
- WhisperLiveKit : https://github.com/QuentinFuxa/WhisperLiveKit/blob/main/LICENSE
- sherpa-onnx : https://github.com/k2-fsa/sherpa-onnx
- DeepFilterNet 0.5.6 : https://github.com/Rikorose/DeepFilterNet/tree/v0.5.6
- FFmpeg (distribution LGPL partagée) : https://github.com/BtbN/FFmpeg-Builds
- Microsoft Visual C++ Redistributable : https://learn.microsoft.com/cpp/windows/latest-supported-vc-redist

Le modèle français Kroko fourni avec sherpa-onnx est à usage **non commercial**.
Cette restriction concerne également l'installateur qui l'embarque. Pour une
utilisation commerciale, remplacer ce modèle et vérifier la licence de son
remplaçant avant distribution. Source :
https://k2-fsa.github.io/sherpa/onnx/pretrained_models/online-transducer/kroko.html

Les licences des composants tiers restent applicables à leur redistribution.
