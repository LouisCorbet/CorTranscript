"""Point d'entrée du backend dans l'interpréteur Python embarqué."""
import argparse


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, required=True)
    args = parser.parse_args()
    import uvicorn
    uvicorn.run('app:app', host='127.0.0.1', port=args.port, access_log=False)


if __name__ == '__main__':
    main()
