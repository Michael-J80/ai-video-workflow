import argparse
import os
import socket
import threading
import webbrowser
import uvicorn


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--no-open', action='store_true')
    args = parser.parse_args()
    # Hold a process-wide port lock before recovery touches persisted state.
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if os.name == 'nt':
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    try:
        sock.bind(('127.0.0.1', 8765))
    except OSError as exc:
        raise SystemExit('端口8765已占用；若应用已运行，请打开 http://127.0.0.1:8765') from exc
    sock.listen(128)
    from .api import create_app
    app = create_app()
    if not args.no_open:
        threading.Timer(1, lambda: webbrowser.open('http://127.0.0.1:8765')).start()
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=8765, log_level='warning'))
    server.run(sockets=[sock])


if __name__ == '__main__':
    main()
