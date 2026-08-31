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


def build_package(
    src: Path,
    requirements: Path,
    dest: Path,
    shared: Path = None,
    platform: str = None,
    python_version: str = None,
) -> None:
    if dest.exists():
        shutil.rmtree(dest, onerror=_handle_remove_readonly)

    dest.mkdir(parents=True, exist_ok=True)

    pip_command = [
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

    # Raciocinio: sem essas flags o pip resolve a wheel nativa (ex: cryptography) compativel
    # com o HOST que roda o build, nao com a arquitetura declarada na Lambda (ex: arm64) — ver
    # app/lambda_cognito_email_sender/lambda_cognito_email_sender.md.
    if platform:
        pip_command += [
            "--platform",
            platform,
            "--implementation",
            "cp",
            "--python-version",
            python_version,
            "--only-binary=:all:",
        ]

    subprocess.check_call(pip_command)

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

    # Copy shared package so `from shared_utils.api_client import ...` works at runtime.
    if shared and shared.is_dir():
        shutil.copytree(
            shared,
            dest / shared.name,
            ignore=shutil.ignore_patterns("__pycache__"),
            dirs_exist_ok=True,
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--src", required=True)
    parser.add_argument("--requirements", required=True)
    parser.add_argument("--dest", required=True)
    parser.add_argument("--shared", default=None, help="Caminho do pacote shared (ex: ../shared_src/shared_utils)")
    parser.add_argument(
        "--platform",
        default=None,
        help="Tag de plataforma pip para cross-compilation (ex: manylinux2014_aarch64). Requer --python-version.",
    )
    parser.add_argument(
        "--python-version",
        default=None,
        help="Versao de Python alvo do pip install (ex: 3.11). Requer --platform.",
    )
    args = parser.parse_args()

    if bool(args.platform) != bool(args.python_version):
        parser.error("--platform e --python-version devem ser passados juntos")

    build_package(
        src=Path(args.src),
        requirements=Path(args.requirements),
        dest=Path(args.dest),
        shared=Path(args.shared) if args.shared else None,
        platform=args.platform,
        python_version=args.python_version,
    )


if __name__ == "__main__":
    main()
