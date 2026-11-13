# CorTranscript

Transcription audio locale en français, en direct ou par morceaux, avec une
interface dans le navigateur. Trois moteurs : Whisper (WhisperX/faster-whisper),
sherpa-onnx et WhisperLiveKit. Réduction de bruit avec DeepFilterNet.

## Installer sur le PC de quelqu'un

Le fichier à lui donner est **`CorTranscript-Setup-1.0.0.exe`**. Il installe
CorTranscript, ses dépendances et ses modèles. Le destinataire n'a besoin ni de
Python, ni de Docker, ni d'une carte NVIDIA. Windows 10/11 **x64** et un navigateur
récent avec accès au microphone sont nécessaires. Prévoir plusieurs Go de disque
et de mémoire vive ; les moteurs tournent sur le CPU.

1. Ouvrir l'installateur et autoriser l'installation Windows.
2. Lancer **CorTranscript** depuis le menu Démarrer ou le raccourci Bureau.
3. Attendre le chargement : l'interface s'ouvre automatiquement dans le navigateur.
4. Autoriser le microphone. Garder la petite fenêtre CorTranscript ouverte pendant
   l'utilisation ; la fermer arrête les moteurs.

Les modèles sont téléchargés **lors de la construction**, pas sur le PC du
destinataire. L'audio est traité localement, sur une adresse `127.0.0.1`.
Les enregistrements, textes et journaux sont conservés dans
`%LOCALAPPDATA%\CorTranscript`. La désinstallation conserve ces données.
L'installateur n'est pas signé : Windows peut afficher un avertissement SmartScreen.

## Construire l'installateur sur Windows

Sur le PC qui construit le logiciel uniquement :

- Installer [Python 3.11 x64](https://www.python.org/downloads/release/python-3119/),
  en conservant le lanceur `py` et Tcl/Tk (options de l'installation standard).
- Installer [Inno Setup 6 ou ultérieur](https://jrsoftware.org/isdl.php).

Puis **double-cliquer sur `build-windows.cmd`**, dans le projet. Le projet peut
être sur le Bureau et son chemin peut contenir des espaces ou des accents.
Une connexion Internet est nécessaire pour cette construction. La première fois,
les bibliothèques et modèles volumineux peuvent prendre un moment à télécharger.

Le résultat est créé dans **`dist\CorTranscript-Setup-1.0.0.exe`**. C'est ce fichier
unique qu'il faut partager. Le script vérifie le démarrage des trois moteurs et
la réduction de bruit avant de produire l'installateur. Il n'inclut ni `.env`, ni
les transcriptions et audios personnels présents dans le dépôt.

Pour changer la version ou le modèle embarqué, depuis PowerShell à la racine :

```powershell
.\build-windows.cmd -Version 1.0.1 -Model small
```

Les choix de modèle sont `tiny`, `base`, `small` (défaut), `medium` et `large-v3`.
Plus le modèle est grand, plus l'installateur et les besoins du PC augmentent.
Le runtime embarqué a ses propres dépendances : aucune modification du Python
utilisé par tes autres projets.

### Construction depuis GitHub

Dans l'onglet **Actions → Windows installer → Run workflow**, choisir la version
et le modèle, puis lancer. À la fin, télécharger l'artefact **CorTranscript-Windows**
et décompresser son ZIP pour récupérer l'installateur `.exe`.
La construction est aussi lancée automatiquement sur les changements applicatifs
poussés dans `main`. Le workflow teste l'installation dans un chemin avec espaces
et accent, puis le lancement sans Python ni Docker dans le `PATH`.

## Utilisation avec Docker

Le lancement Docker reste disponible :

```sh
docker compose up --build -d
```

Puis ouvrir http://localhost:8000. Les réglages de modèles restent ceux de `.env`
et de `docker-compose.yml`. Journaux : `docker compose logs -f cortranscript wlk`.

Après une mise à jour depuis l'ancien nom, utiliser `docker compose up --build -d
--remove-orphans` pour arrêter l'ancien conteneur. Les moteurs WhisperX et
WhisperLiveKit conservent leurs noms : ce sont les bibliothèques utilisées.

## Composants et modèles

Le modèle français Kroko déjà utilisé par le projet est soumis à une licence
**non commerciale**. Cette restriction s'applique également à l'installateur qui
l'embarque. Voir [les composants tiers](packaging/THIRD_PARTY.md) et le
`build-manifest.json` fourni dans l'installation pour les versions distribuées.


## Documentation technique

### Architecture et responsabilités

CorTranscript est une application web locale. Le navigateur capture l'audio et
affiche les résultats ; les moteurs Python exécutent la transcription sur la
machine qui héberge le backend.

| Composant | Rôle |
| --- | --- |
| `index.html` | Interface, capture micro/audio système selon les possibilités du navigateur, envoi audio, affichage et édition |
| `app.py` | Serveur FastAPI, WebSockets, orchestration des moteurs, fichiers et traitements par morceaux |
| WhisperX + faster-whisper | Transcription Whisper en live et par morceaux |
| sherpa-onnx | Reconnaissance en streaming avec le modèle français Kroko |
| WhisperLiveKit | Serveur séparé, utilisé par le backend comme moteur live supplémentaire |
| DeepFilterNet | Réduction de bruit facultative ; ce composant ne transcrit pas |
| FFmpeg | Outil audio embarqué dans la distribution Windows et installé dans les images Docker |

Les flux audio live sont du PCM mono, signé 16 bits, à **16 kHz**. Le backend
convertit les échantillons en tableaux NumPy pour les moteurs qui en ont besoin.
L'interface communique avec FastAPI en HTTP et WebSocket. Pour WhisperLiveKit,
FastAPI relaie le flux vers le WebSocket `/asr` du second serveur.

### Modèles utilisés et différences entre les modes

Le **modèle** désigne les poids de reconnaissance vocale ; le **moteur** est le
logiciel qui les exécute. WhisperX et WhisperLiveKit sont des moteurs/pipelines :
leur nom ne désigne pas un modèle différent de Whisper.

Avec la configuration actuelle (`WHISPER_MODEL=small`, langue `fr`) :

| Mode / choix dans l'interface | Moteur | Modèle réellement utilisé | Fonctionnement |
| --- | --- | --- | --- |
| Live — Whisper | WhisperX, qui s'appuie sur faster-whisper/CTranslate2 | Whisper multilingue **small**, calcul CPU `int8` | Réévaluation de fenêtres audio et finalisation après les pauses ; `beam_size=1` |
| Live — Streaming temps réel | sherpa-onnx | **sherpa-onnx-streaming-zipformer-fr-kroko-2025-08-06** | Modèle français de streaming, constitué d'un encodeur, d'un décodeur et d'un joiner ONNX, avec `tokens.txt` |
| Live — WhisperLiveKit | faster-whisper dans WhisperLiveKit, stratégie **LocalAgreement** | Le même choix de modèle Whisper : **small** par défaut | Fenêtres successives et stabilisation progressive du texte |
| Par morceaux | faster-whisper, appelé directement depuis le backend | Le même modèle Whisper **small**, CPU `int8` | Traitement de chaque fichier WAV, `beam_size=5`, détection de voix et horodatage des mots |

**Le sélecteur de moteur live ne change pas le moteur du mode par morceaux.**
Le mode par morceaux utilise toujours faster-whisper et le modèle choisi par
`WHISPER_MODEL` (Docker) ou `-Model` à la construction de l'installateur.

Dans `app.py`, `get_fw()` récupère si possible le modèle faster-whisper déjà chargé
par WhisperX ; il en crée une instance de même configuration si nécessaire.
Le mode live Whisper et le mode par morceaux partagent donc le même choix de
poids, avec des paramètres de décodage différents. WhisperLiveKit charge son
propre exemplaire dans un autre processus.

Le live Whisper utilise également **Silero VAD** pour la détection de voix. Le
mode par morceaux active le filtre VAD de faster-whisper avec
`vad_filter=True`. Ces détecteurs repèrent la parole ; ils ne remplacent pas le
modèle de transcription. Le live Whisper utilise notamment une pause de
`0.8 s` pour clore une phrase, un intervalle partiel initial de `1.5 s` et une
fenêtre maximale de `15 s` ; l'intervalle partiel peut augmenter si le calcul
prend du retard.

La réduction de bruit DeepFilterNet est facultative :

- en live Whisper : appliquée à la version finale de la phrase ; l'aperçu
  partiel utilise l'audio brut ;
- en mode par morceaux : appliquée au fichier avant transcription ;
- en live sherpa-onnx ou WhisperLiveKit : désactivée dans l'interface.

### Configuration : Docker et Windows

| Réglage | Docker | Installateur Windows |
| --- | --- | --- |
| Modèle Whisper | `WHISPER_MODEL` dans `.env` ; défaut `small` | Paramètre de construction `-Model` ; défaut `small` |
| Langue | `WHISPER_LANGUAGE` ; `fr` actuellement, `auto` accepté par le backend | `fr` imposé par le lanceur |
| Calcul Whisper du backend | `WHISPER_DEVICE=cpu`, `WHISPER_COMPUTE_TYPE=int8` | CPU, `int8` ; GPU masqué avec `CUDA_VISIBLE_DEVICES=-1` |
| Recherche par morceaux | `WHISPER_BEAM_CHUNKS=5` dans Compose | `WHISPER_BEAM_CHUNKS=5` injecté par le lanceur |
| Modèle sherpa-onnx | `SHERPA_MODEL` passé à la construction de l'image | Kroko FR fixé dans `packaging/prepare_models.py` |
| Adresse WhisperLiveKit | `ws://wlk:8000/asr` sur le réseau Docker | Adresse `127.0.0.1` et port local choisi au lancement |
| Configuration effective | `.env` et `docker-compose.yml` | `config.json` embarqué et variables injectées par `packaging/launcher.py` |

Le programme installé ne lit pas le `.env` du dépôt. Modifier ce fichier ne
modifie donc pas un installateur déjà construit.

Pour Docker, reconstruire après un changement de modèle :

```sh
docker compose up --build -d
```

Pour embarquer un autre modèle Whisper dans Windows :

```powershell
.\build-windows.cmd -Version 1.0.1 -Model medium
```

Ce paramètre remplace le modèle de Whisper **pour le live Whisper, le live
WhisperLiveKit et le mode par morceaux**. Il ne modifie pas le modèle Kroko.
Dans `windows_server.py`, WhisperLiveKit reçoit le chemin local via
`--model_dir` : ce chemin détermine les poids chargés, même si l'argument
`--model small` est aussi présent.

### Construction de la distribution Windows

Le point d'entrée utilisateur est `build-windows.cmd`, qui appelle
`scripts/build-windows.ps1` avec les paramètres reçus. Le script utilise les
chemins du projet et fonctionne depuis un dossier contenant des espaces ou des
accents.

| Étape | Traitement |
| --- | --- |
| 1 | Vérification de Python 3.11 x64 et d'Inno Setup ; préparation d'un Python embarqué 3.11.9 et installation des dépendances CPU |
| 2 | Intégration des binaires Windows FFmpeg et DeepFilterNet, et de l'installateur Microsoft Visual C++ Redistributable |
| 3 | Copie explicite de `app.py`, `index.html` et `windows_server.py` |
| 4 | Téléchargement du modèle Whisper, du cache Silero et du modèle sherpa-onnx ; essai de transcription sur un signal silencieux |
| 5 | Construction du lanceur graphique avec PyInstaller et écriture de `build-manifest.json` |
| 6 | Démarrage des serveurs, vérification de disponibilité des trois moteurs et essai de réduction de bruit WAV |
| 7 | Production de l'installateur unique avec Inno Setup |

PyInstaller construit **le lanceur graphique**. Les bibliothèques de
reconnaissance sont placées dans un interpréteur Python embarqué séparé, sous
`runtime/`. Elles conservent leurs modules et leurs ressources de package, sans
dépendre du Python du destinataire.

| Chemin dans le dépôt | Contenu |
| --- | --- |
| `packaging/requirements-windows.txt` | Dépendances de la distribution Windows ; plusieurs versions directes sont fixées |
| `packaging/prepare_models.py` | Préchargement et validation des modèles |
| `packaging/launcher.py` | Fenêtre de démarrage, instance unique, processus, ouverture du navigateur et arrêt |
| `packaging/windows_server.py` | Points d'entrée des serveurs FastAPI et WhisperLiveKit |
| `packaging/CorTranscript.iss` | Installation, raccourcis, runtime Microsoft et désinstallation |
| `build/windows/CorTranscript/` | Distribution préparée avant création de l'installateur |
| `.packaging-cache/` | Archives et binaires téléchargés, réutilisés si déjà présents |
| `dist/` | Installateurs à distribuer |
| `.github/workflows/windows-installer.yml` | Construction et contrôles sous Windows sur GitHub |

Le manifeste conserve la version applicative, le modèle demandé, la version de
Python, la provenance FFmpeg et les versions des packages réellement installés.
La construction n'est pas entièrement verrouillée : certaines dépendances
transitives et certains téléchargements suivent les versions disponibles au
moment du build. Le manifeste permet d'identifier le contenu de chaque paquet.

### Installation et démarrage Windows

L'installateur place par défaut le logiciel sous
`%ProgramFiles%\CorTranscript`, demande les droits administrateur et installe le
runtime Microsoft Visual C++ si nécessaire. Les raccourcis lancent
`CorTranscript.exe`.

Au démarrage, le lanceur :

1. prend un verrou par utilisateur pour éviter le chargement de plusieurs instances ;
2. prépare les dossiers de données et le cache Torch de l'utilisateur ;
3. choisit deux ports locaux libres et démarre FastAPI et WhisperLiveKit ;
4. attend les réponses de `/api/health` et du `/health` de WhisperLiveKit ;
5. ouvre le navigateur sur l'adresse du backend.

Les deux serveurs Windows écoutent sur `127.0.0.1`. Le port peut changer à chaque
lancement. Dans Docker, seul FastAPI est publié sur `127.0.0.1:8000` ;
WhisperLiveKit reste accessible depuis le réseau interne Compose.

Fermer la fenêtre du lanceur arrête les processus et leurs enfants. Il faut
terminer les enregistrements avant de fermer.

### Données et persistance

| Donnée | Windows | Docker |
| --- | --- | --- |
| Audios et métadonnées | `%LOCALAPPDATA%\CorTranscript\audio` | `./audio` monté dans `/audio` |
| Transcriptions texte et sessions JSON | `%LOCALAPPDATA%\CorTranscript\transcriptions` | `./transcriptions` monté dans `/transcriptions` |
| Journaux des serveurs | `%LOCALAPPDATA%\CorTranscript\logs\app.log` et `wlk.log` | Sortie des services, consultable avec `docker compose logs` |
| Cache utilisateur Windows | `%LOCALAPPDATA%\CorTranscript\cache` | Les modèles principaux sont préchargés dans les images |

En live, les phrases finalisées sont écrites dans un fichier texte ; le mode live
ne conserve pas l'audio pour la consultation ultérieure. Le mode par morceaux
conserve les WAV, des métadonnées JSON et les transcriptions de session avec
segments et horodatage des mots. Le backend tente de récupérer les fichiers
`.pcm.part` interrompus lors de son prochain démarrage.

L'état du traitement et le réglage de réduction de bruit sont conservés en
mémoire dans le backend. Les fichiers audio et les transcriptions persistent
indépendamment de cet état. La désinstallation Windows conserve le dossier
utilisateur ; supprimer ce dossier efface ces données.

### Interfaces du backend

| Route | Usage |
| --- | --- |
| `GET /api/health` | Identification de CorTranscript et état prêt |
| `GET /api/engines` | Moteurs live disponibles et disponibilité de DeepFilterNet |
| `WS /ws?engine=whisper` | Live Whisper ; les autres identifiants sont `sherpa` et `whisperlivekit` |
| `WS /ws/record` | Réception de l'audio pour les enregistrements par morceaux |
| `GET /api/state` | Audios, état du traitement et réglages |
| `POST /api/settings` | Réglage de réduction de bruit |
| `POST /api/transcribe/start` | Traitement des enregistrements en attente |
| `POST /api/transcribe/cancel` | Demande d'annulation du traitement |
| `GET /api/sessions` | Liste des sessions |
| `POST /api/live/edit` | Enregistrement des corrections du texte live |
| `POST /denoise` | Réduction de bruit d'un WAV pour comparaison |

Cette table présente les principaux points d'entrée ; les fonctions de
consultation, suppression et restauration sont détaillées dans `app.py`.

### Vérification et diagnostic

Les tests des utilitaires de packaging se lancent depuis la racine :

```sh
python -m unittest discover -s tests -v
```

La construction lance un contrôle des services et du traitement DeepFilterNet.
Le workflow GitHub ajoute une installation silencieuse dans un dossier avec
espaces et accent, puis exécute le lanceur installé avec un `PATH` limité aux
dossiers système Windows.

Le contrôle peut aussi être lancé manuellement depuis le dossier d'installation :

```powershell
.\CorTranscript.exe --smoke-test
```

Son journal se trouve dans `%TEMP%\CorTranscript-smoke.log`. Ce contrôle utilise
un dossier de données temporaire et arrête ses serveurs à la fin.
Il vérifie le chargement et la disponibilité des moteurs ainsi qu'un traitement
de réduction de bruit ; il ne mesure pas la précision de transcription sur un
corpus parlé.

En utilisation normale, le bouton **Ouvrir les journaux** donne accès à
`app.log` et `wlk.log`. Pour Docker :

```sh
docker compose logs -f cortranscript wlk
```

Un moteur marqué indisponible doit être diagnostiqué dans les journaux avant
de reconstruire. Pour un problème de modèle ou de dépendance sur une version
installée, relever aussi le `build-manifest.json` du dossier d'installation.
