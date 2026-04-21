"""Build lambda package directory with application source and pip dependencies."""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def build_package(src: Path, requirements: Path, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)

    shutil.copytree(src, dest)

    subprocess.check_call(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "-r",
            str(requirements),
            "-t",
            str(dest),
            "--upgrade",
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--src", required=True)
    parser.add_argument("--requirements", required=True)
    parser.add_argument("--dest", required=True)
    args = parser.parse_args()

    build_package(
        src=Path(args.src),
        requirements=Path(args.requirements),
        dest=Path(args.dest),
    )


if __name__ == "__main__":
    main()
