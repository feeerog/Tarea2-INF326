"""Regenera los stubs usando la misma versión fijada de grpcio-tools."""

import subprocess
import sys
from pathlib import Path

import grpc_tools

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    subprocess.run(
        [
            sys.executable,
            "-m",
            "grpc_tools.protoc",
            f"-I{ROOT / 'proto'}",
            f"-I{Path(grpc_tools.__file__).parent / '_proto'}",
            f"--python_out={ROOT}",
            f"--grpc_python_out={ROOT}",
            str(ROOT / "proto/shortener/generated/hits.proto"),
        ],
        check=True,
    )
    print("Stubs gRPC generados en shortener/generated/")


if __name__ == "__main__":
    main()
