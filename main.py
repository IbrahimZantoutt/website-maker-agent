"""
Multi-Agent System v2 — Entry point.

Usage:
    python main.py
    python main.py --port 8080
"""
import argparse
from ui import start_ui

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Multi-Agent Dev System v2")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8000, help="Port to listen on")
    args = parser.parse_args()

    print(f"\n  Multi-Agent System v2")
    print(f"  Open http://localhost:{args.port} in your browser\n")

    start_ui(host=args.host, port=args.port)
