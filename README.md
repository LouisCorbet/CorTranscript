# CorTranscript

Transcription audio locale en français, en direct avec **Kroko FR** ou par
morceaux avec **Whisper**. L'interface fonctionne dans le navigateur et permet de
mélanger plusieurs entrées audio, par exemple le son d'une visio et un micro.

## Modèles et traitements

| Mode | Moteur | Modèle et paramètres |
| --- | --- | --- |
| Live | sherpa-onnx | `sherpa-onnx-streaming-zipformer-fr-kroko-2025-08-06`, streaming français, CPU |
| Par morceaux | faster-whisper / CTranslate2 | Whisper multilingue `small` par défaut, CPU `int8`, `beam_size=5`, VAD et horodatage des mots |
| Réduction de bruit des morceaux | DeepFilterNet 0.5.6 | Traitement facultatif du WAV avant transcription, avec outil de comparaison audio |

Kroko est le seul moteur live. Whisper est chargé à la première transcription
par morceaux, puis réutilisé. Son modèle se règle dans `.env` avec Docker ou avec
`-Model` lors de la construction de l'installateur. Ce réglage ne modifie pas Kroko.

## Mélanger les entrées audio

La sélection est partagée entre le live, l'enregistrement par morceaux et le
test de réduction de bruit.

1. Cliquer sur **Actualiser les micros** pour autoriser leur accès et afficher
   leurs noms si nécessaire.
2. Cocher un ou plusieurs micros / périphériques d'entrée.
3. Pour une visio, cocher également **Son de l'ordinateur / visio**.
4. Cliquer sur **Tester**, **Démarrer** ou **Enregistrer**. Si le son de
   l'ordinateur est coché, le navigateur demande alors quoi partager : choisir
   l'onglet de la visio ou l'écran et activer **Partager l'audio**.
5. Vérifier la liste des sources actives et le niveau du mélange.

Un partage ne contenant aucune piste audio est refusé avec un message explicite.
L'offre de partage audio dépend du navigateur, du système et de la surface
choisie ; le programme ne peut pas activer une option que le navigateur ne
propose pas. Pour la capture d'une visio sous Windows, utiliser un navigateur
proposant le partage audio d'un onglet ou du système. Référence :
[Screen Capture API](https://developer.mozilla.org/en-US/docs/Web/API/Screen_Capture_API/Using_Screen_Capture).

Un casque évite de reprendre les interlocuteurs une seconde fois dans le micro.
Les voix de toutes les sources produisent **une seule transcription du mélange**,
sans attribution du texte à chaque source.

Si une source s'arrête, l'interface le signale et les autres continuent. Si elles
s'arrêtent toutes, la capture s'arrête. L'arrêt d'un test ou d'un enregistrement
libère les micros et le partage ; un prochain démarrage demandera un nouveau
partage audio. Si une autorisation échoue pendant la préparation, les sources
déjà ouvertes sont libérées.

## Installer sur un PC Windows

Distribuer **`CorTranscript-Setup-1.1.0.exe`**, généré localement dans `dist/`
avec le script de construction. Python, les bibliothèques et les modèles sont embarqués.
Le destinataire n'a besoin d'installer ni Python ni Docker ni CUDA.

1. Ouvrir l'installateur et autoriser l'installation.
2. Lancer **CorTranscript** depuis le menu Démarrer ou le raccourci Bureau.
3. Attendre le chargement de Kroko et l'ouverture du navigateur.
4. Sélectionner les entrées audio. Garder la fenêtre du lanceur ouverte pendant
   l'utilisation ; sa fermeture arrête le backend.

Windows 10/11 x64 et un navigateur récent avec accès au microphone sont requis.
Les traitements se font sur le CPU. L'installateur n'est pas signé : Windows
peut afficher un avertissement SmartScreen.

## Construire l'installateur localement

La construction est manuelle : elle démarre uniquement lorsque tu exécutes
`build-windows.cmd` sur ton PC Windows. Le dépôt ne contient aucun workflow
GitHub Actions ; un push ne lance ni script, ni test, ni construction.

Sur le PC de construction uniquement, installer :

- [Python 3.11 x64](https://www.python.org/downloads/release/python-3119/), avec
  le lanceur `py` et Tcl/Tk de l'installation standard ;
- [Inno Setup 6](https://jrsoftware.org/isdl.php) ou une version compatible.

Puis **double-cliquer sur `build-windows.cmd`** à la racine. Le projet peut se
trouver sur le Bureau, dans un chemin contenant des espaces et des accents.
Une connexion Internet est nécessaire pour télécharger les bibliothèques et modèles.

Le script recrée automatiquement son environnement d’outils à chaque lancement.
Les bibliothèques natives sont sélectionnées explicitement pour **CPython 3.11.9
Windows x64**, avec PyAV 15.1.0. L’import de `av._core` est vérifié dans le Python
embarqué avant le téléchargement des modèles.

Pour personnaliser la version et le modèle Whisper, depuis PowerShell :

```powershell
.\build-windows.cmd -Version 1.1.0 -Model medium
```

Choix de modèle : `tiny`, `base`, `small` (défaut), `medium`, `large-v3`.
Le résultat est `dist\CorTranscript-Setup-<version>.exe`. C'est le fichier unique
à partager. Les audios, transcriptions et `.env` du développeur sont exclus du paquet.

## Utilisation Docker

```sh
docker compose up --build -d --remove-orphans
```

Ouvrir [http://localhost:8000](http://localhost:8000). Il reste un seul service,
`cortranscript`. `--remove-orphans` arrête les anciens services du même projet
Compose devenus inutiles après la mise à jour. Les fichiers montés sont conservés.

```sh
docker compose logs -f cortranscript
```

`.env` configure le modèle Whisper et sa langue (`fr` actuellement) ainsi que
l'archive Kroko téléchargée pendant le build. Reconstruire après un changement de
modèle. Le programme installé sous Windows ne lit pas ce `.env`.

## Architecture technique

| Fichier | Responsabilité |
| --- | --- |
| `index.html` | Interface, sélection des entrées, affichage, édition, enregistrement PCM et consultation des transcriptions |
| `audio-inputs.js` | Acquisition de plusieurs sources, mélange Web Audio, gestion de fin de piste et libération des ressources |
| `app.py` | FastAPI, WebSockets, Kroko live, traitement des WAV par Whisper et persistance |
| `requirements.txt` | Dépendances communes Docker / Windows : moteurs CPU, API, NumPy et bibliothèques audio |
| `bake_models.py` | Préchargement du modèle Whisper dans l'image Docker |
| `packaging/prepare_models.py` | Préchargement des modèles Whisper et Kroko pour Windows, validation du chemin Whisper |
| `packaging/launcher.py` | Fenêtre Windows, instance unique, démarrage du backend, navigateur et arrêt des processus |
| `packaging/windows_server.py` | Point d'entrée FastAPI dans le Python embarqué |
| `packaging/CorTranscript.iss` | Installation, raccourcis, runtime Microsoft et désinstallation |
| `scripts/build-windows.ps1` | Assemblage des dépendances, modèles, lanceur et installateur |

### Chaîne audio

Le navigateur acquiert chaque entrée indépendamment. Les pistes audio sont
converties en mono et sommées dans un même graphe Web Audio à 16 kHz. Le gain du
mélange réserve une marge selon le nombre de sources, puis un compresseur réduit
la saturation lorsque plusieurs sources parlent simultanément. Le graphe
n'envoie pas le son capturé vers les haut-parleurs.

Le résultat passe dans un AudioWorklet qui produit du PCM mono signé 16 bits,
16 kHz. Ce flux unique est envoyé à FastAPI :

- `/ws` : Kroko décode progressivement et produit des textes partiels puis finaux ;
- `/ws/record` : le backend écrit des morceaux WAV, ensuite traités par Whisper.

La capture d'écran reste active pendant le partage, comme l'exige l'API du
navigateur, mais **aucune vidéo n'est envoyée au backend**. Le test de niveau et
la comparaison DeepFilterNet utilisent le même mélange que la transcription.

### Exécution et configuration Windows

Le lanceur choisit un port libre sur `127.0.0.1`, démarre un seul backend avec son
interpréteur embarqué, attend `/api/health`, puis ouvre le navigateur. Le modèle
Kroko est chargé au démarrage ; Whisper est initialisé seulement à la première
transcription par morceaux.

Le lanceur impose le français, le calcul CPU et `int8` pour Whisper, ainsi que
`WHISPER_BEAM_CHUNKS=5`. `WHISPER_MODEL` désigne le dossier local du modèle
embarqué ; `SHERPA_MODEL_DIR` désigne les fichiers ONNX Kroko. Les variables
`AUDIO_DIR`, `TRANSCRIPTIONS_DIR` et `DEEPFILTER_BIN` pointent vers les données
utilisateur et le binaire de réduction de bruit. Les requêtes Hugging Face sont
configurées en mode hors ligne pour le programme installé.

L'installation se fait par défaut dans `%ProgramFiles%\CorTranscript` et requiert
les droits administrateur. Elle inclut le runtime Microsoft Visual C++.
Une réinstallation remplace les dossiers applicatifs pour retirer les anciennes
bibliothèques et les anciens modèles ; le dossier de données utilisateur est conservé.

### Assemblage et versions

Le build utilise Python embarqué 3.11.9 et installe les dépendances dans son
`runtime/Lib/site-packages`. PyInstaller construit uniquement le lanceur graphique.
Inno Setup regroupe le lanceur, l'interpréteur, le backend, les modèles et
DeepFilterNet dans l'installateur.

| Chemin | Contenu |
| --- | --- |
| `build/windows/CorTranscript/` | Distribution avant compression |
| `.packaging-cache/` | Archives et binaires téléchargés réutilisables |
| `dist/` | Installateurs à partager |
| `build-manifest.json` dans l'installation | Version applicative, modèle Whisper, version de Python, DeepFilterNet et packages réellement installés |
| `config.json` dans l'installation | Identité des modèles téléchargés |

Certaines dépendances transitives suivent les versions disponibles au build :
le manifeste permet d'identifier le contenu exact d'un installateur donné.
Les modèles sont téléchargés pendant la construction.

### Persistance

| Données | Windows | Docker |
| --- | --- | --- |
| WAV et métadonnées | `%LOCALAPPDATA%\CorTranscript\audio` | `./audio` monté dans `/audio` |
| Textes et sessions JSON | `%LOCALAPPDATA%\CorTranscript\transcriptions` | `./transcriptions` monté dans `/transcriptions` |
| Journal backend | `%LOCALAPPDATA%\CorTranscript\logs\app.log` | `docker compose logs` |
| Cache utilisateur | `%LOCALAPPDATA%\CorTranscript\cache` | Modèles préchargés dans l'image |

En live, les phrases finales et les corrections sont enregistrées en texte ;
l'audio live n'est pas conservé. Par morceaux, les WAV, les textes, les segments
et les horodatages des mots sont conservés. Le backend tente de récupérer les
fichiers `.pcm.part` interrompus au démarrage suivant.

Le réglage de réduction de bruit et l'état du traitement sont en mémoire. La
désinstallation conserve le dossier de données Windows de l'utilisateur.

### API principale

| Route | Usage |
| --- | --- |
| `GET /api/health` | Identification et état du backend |
| `GET /api/engines` | Disponibilité de Kroko et de DeepFilterNet |
| `GET /audio-inputs.js` | Script de capture et de mélange |
| `WS /ws` | Live Kroko ; message `{"stop":true}` pour finaliser |
| `WS /ws/record` | Enregistrement ; messages `{"cut":true}` et `{"stop":true}` |
| `GET /api/state` | Audios, traitement en cours et réglages |
| `POST /api/settings` | Réglage DeepFilterNet des morceaux |
| `POST /api/transcribe/start` | Traitement des enregistrements en attente |
| `POST /api/transcribe/cancel` | Annulation |
| `GET /api/sessions` | Consultation des sessions |
| `POST /api/live/edit` | Corrections du texte live |
| `POST /denoise` | Comparaison d'un WAV avec / sans réduction de bruit |

### Tests et diagnostic

Tests backend et utilitaires, sans téléchargement de modèles de parole :

```sh
python -m pip install -r requirements.txt httpx
python -m unittest discover -s tests -v
```

Pour inclure les tests du mélange réel dans Chromium :

```sh
python -m pip install playwright
python -m playwright install chromium
python -m unittest discover -s tests -v
```

Les entrées des tests navigateur sont des signaux générés : ils vérifient le
mélange, la perte d'une source, les refus d'autorisation, l'annulation et la
libération des périphériques. Ils ne remplacent pas un essai de partage audio
d'une vraie visio sur le navigateur du destinataire.

Les commandes ci-dessus exécutent les tests manuellement sur ton PC.
Lorsque tu lances `build-windows.cmd`, le script local vérifie les modèles
embarqués, Kroko, DeepFilterNet et une transcription par morceaux sur un WAV
silencieux avant de produire l'installateur.

Depuis le dossier d'installation, pour rejouer ce diagnostic :

```powershell
.\CorTranscript.exe --smoke-test
```

Journal : `%TEMP%\CorTranscript-smoke.log`. Le contrôle utilise des données
temporaires, puis arrête son backend. Il valide le fonctionnement technique,
sans mesurer la précision sur un corpus parlé.

En utilisation normale, le bouton **Ouvrir les journaux** donne accès à `app.log`.
Joindre aussi `build-manifest.json` pour identifier la version exacte distribuée.

## Composants tiers

Le modèle Kroko fourni est sous licence **non commerciale**. Voir
[les composants tiers](packaging/THIRD_PARTY.md) pour les sources et licences.
