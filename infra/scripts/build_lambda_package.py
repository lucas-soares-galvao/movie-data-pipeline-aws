"""Raciocinio: monta pacote da Lambda com codigo e dependencias para deploy deterministico no Terraform."""

import argparse
import os
import shutil
import subprocess
import sys
import stat
from pathlib import Path


def _handle_remove_readonly(func, path, exc_info):
    _ = exc_info
    os.chmod(path, stat.S_IWRITE)
    func(path)


def build_package(src: Path, requirements: Path, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest, onerror=_handle_remove_readonly)

    dest.mkdir(parents=True, exist_ok=True)

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

    # Copy application source directly to dest so `from src.utils import ...`
    # works at Lambda runtime (mirrors the Glue --extra-py-files layout).
    for item in src.iterdir():
        if item.name == "__pycache__":
            continue
        target = dest / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        else:
            shutil.copy2(item, target)


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
