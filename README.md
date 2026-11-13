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
