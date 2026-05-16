"""Build lambda package directory with application source and pip dependencies."""

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

    # Keep app package namespace in the deployment artifact so imports like
    # `from app.lambda_api.src.utils import ...` work at Lambda runtime.
    app_root = src.parent
    package_root = dest / "app"
    package_root.mkdir(parents=True, exist_ok=True)

    app_init = app_root / "__init__.py"
    if app_init.exists():
        shutil.copy2(app_init, package_root / "__init__.py")

    shutil.copytree(src, package_root / src.name, dirs_exist_ok=True)


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
