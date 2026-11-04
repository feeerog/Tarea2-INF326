"""Inicia los tres procesos y los cierra con Ctrl+C, también en Windows."""

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    os.chdir(ROOT)
    subprocess.run([sys.executable, "scripts/generate_certs.py"], check=True)
    processes = []
    try:
        for service in ("log", "v1", "v2"):
            processes.append(subprocess.Popen([sys.executable, "-m", "shortener", service]))
        print("v1: https://localhost:8443/schema | v2: https://localhost:8444/schema", flush=True)
        print("Ctrl+C detiene los tres servicios.", flush=True)
        while True:
            for process in processes:
                if process.poll() is not None:
                    raise RuntimeError(f"Un servicio terminó con código {process.returncode}")
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nDeteniendo servicios...", flush=True)
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == "__main__":
    main()
