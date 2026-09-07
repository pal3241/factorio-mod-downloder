import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description="Factorio Mod Manager launcher")
    parser.add_argument("mode", nargs="?", choices=["app", "flet-web", "web"], default="app")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    if args.mode in {"app", "flet-web"}:
        import flet as ft
        from flet_app import main as flet_main
        if args.mode == "flet-web":
            ft.run(flet_main, view=ft.AppView.WEB_BROWSER, host=args.host, port=args.port or 8550)
        else:
            ft.run(flet_main, view=ft.AppView.FLET_APP)
        return

    from app import app
    app.run(host=args.host, port=args.port or 5000, debug=False)


if __name__ == "__main__":
    main()
