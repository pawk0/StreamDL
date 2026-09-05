import sys

from server.app import run_server

if __name__ == "__main__":
    try:
        run_server()
    except KeyboardInterrupt:
        print("\nShutting down server...")
        sys.exit(0)
