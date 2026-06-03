"""Raciocinio: empacota o pacote `src` de um job Glue Python Shell como wheel (.whl).

Jobs Glue Python Shell nao adicionam arquivos .zip ao sys.path via --extra-py-files
(somente jobs Spark/PySpark fazem isso). O formato suportado e .whl. Este script gera,
de forma deterministica, um wheel contendo apenas o pacote `src` do app, para que o
`from src.utils import ...` no main.py funcione em runtime.

As dependencias de runtime (ex.: awswrangler) continuam vindo de --additional-python-modules,
por isso o wheel e construido com --no-deps.
"""

import argparse
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

# Nome de arquivo deterministico do artefato final (independente de versao/nome da dist).
OUTPUT_WHEEL_NAME = "app_bundle.whl"


def _handle_remove_readonly(func, path, exc_info):
    _ = exc_info
    os.chmod(path, stat.S_IWRITE)
    func(path)


def build_wheel(src: Path, dest: Path, name: str) -> None:
    if dest.exists():
        shutil.rmtree(dest, onerror=_handle_remove_readonly)
    dest.mkdir(parents=True, exist_ok=True)

    src_package = src / "src"
    if not src_package.is_dir():
        raise FileNotFoundError(f"Pacote 'src' nao encontrado em: {src_package}")

    with tempfile.TemporaryDirectory() as staging_str:
        staging = Path(staging_str)

        # Copia o pacote `src` para o staging (sem __pycache__).
        shutil.copytree(
            src_package,
            staging / "src",
            ignore=shutil.ignore_patterns("__pycache__"),
        )

        # pyproject.toml minimo declarando o pacote `src`.
        (staging / "pyproject.toml").write_text(
            "[build-system]\n"
            'requires = ["setuptools>=61.0"]\n'
            'build-backend = "setuptools.build_meta"\n'
            "\n"
            "[project]\n"
            f'name = "{name}"\n'
            'version = "0.0.0"\n'
            "\n"
            "[tool.setuptools]\n"
            'packages = ["src"]\n',
            encoding="utf-8",
        )

        # Constroi o wheel sem dependencias (deps vem de --additional-python-modules).
        subprocess.check_call(
            [
                sys.executable,
                "-m",
                "pip",
                "wheel",
                str(staging),
                "--no-deps",
                "-w",
                str(dest),
            ]
        )

    wheels = list(dest.glob("*.whl"))
    if not wheels:
        raise RuntimeError(f"Nenhum wheel gerado em: {dest}")

    # Renomeia para um nome deterministico usado pelo Terraform / --extra-py-files.
    built = wheels[0]
    final = dest / OUTPUT_WHEEL_NAME
    if final.exists():
        final.unlink()
    built.rename(final)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--src", required=True, help="Diretorio do app (contem a pasta src/)")
    parser.add_argument("--dest", required=True, help="Diretorio de saida do wheel")
    parser.add_argument("--name", required=True, help="Nome da distribuicao do wheel")
    args = parser.parse_args()

    build_wheel(src=Path(args.src), dest=Path(args.dest), name=args.name)


if __name__ == "__main__":
    main()
