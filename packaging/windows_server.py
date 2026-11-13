"""Run with the private embedded interpreter, never with the launcher's Python."""
import argparse
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['app', 'wlk'])
    parser.add_argument('--port', type=int, required=True)
    args = parser.parse_args()
    if args.mode == 'app':
        import uvicorn
        uvicorn.run('app:app', host='127.0.0.1', port=args.port, access_log=False)
    else:
        import sys
        # Use the server entry point directly; pip-generated .exe scripts can
        # contain the build machine's interpreter path.
        sys.argv = ['whisperlivekit-server', '--host', '127.0.0.1', '--port', str(args.port),
                    '--pcm-input', '--backend', 'faster-whisper',
                    '--backend-policy', 'localagreement', '--model', 'small',
                    '--model_dir', os.environ['WHISPER_MODEL'], '--language', 'fr']
        from whisperlivekit.basic_server import main as wlk_main
        wlk_main()


if __name__ == '__main__':
    main()
