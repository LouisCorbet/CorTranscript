# Composants tiers de CorTranscript

L'installateur contient Python, faster-whisper / CTranslate2,
sherpa-onnx, DeepFilterNet, PyAV et leurs dépendances.
Les mentions et licences des packages sont conservées dans leurs dossiers
`*.dist-info` sous `runtime/Lib/site-packages`, celles de Python dans `runtime`,
ainsi que dans les fichiers de licence fournis avec les bibliothèques natives.
Le manifeste `build-manifest.json` indique les versions effectivement distribuées.

- Python : https://www.python.org/doc/copyright/
- faster-whisper : https://github.com/SYSTRAN/faster-whisper/blob/master/LICENSE
- sherpa-onnx : https://github.com/k2-fsa/sherpa-onnx
- DeepFilterNet 0.5.6 : https://github.com/Rikorose/DeepFilterNet/tree/v0.5.6
- PyAV (et les bibliothèques FFmpeg de ses wheels) : https://github.com/PyAV-Org/PyAV
- Microsoft Visual C++ Redistributable : https://learn.microsoft.com/cpp/windows/latest-supported-vc-redist

Le modèle français Kroko fourni avec sherpa-onnx est à usage **non commercial**.
Cette restriction concerne également l'installateur qui l'embarque. Pour une
utilisation commerciale, remplacer ce modèle et vérifier la licence de son
remplaçant avant distribution. Source :
https://k2-fsa.github.io/sherpa/onnx/pretrained_models/online-transducer/kroko.html

Les licences des composants tiers restent applicables à leur redistribution.
