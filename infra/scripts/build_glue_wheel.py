"""Raciocinio: empacota o pacote `src` de um job Glue Python Shell como wheel (.whl).

Jobs Glue Python Shell nao adicionam arquivos .zip ao sys.path via --extra-py-files
(somente jobs Spark/PySpark fazem isso). O formato suportado e .whl. Este script gera,
de forma deterministica, um wheel contendo apenas o pacote `src` do app, para que o
`from src.utils import ...` no main.py funcione em runtime.

As dependencias de runtime (ex.: awswrangler) continuam vindo de --additional-python-modules,
por isso o wheel e construido com --no-deps.

O Glue Python Shell faz `pip install` do wheel passado em --extra-py-files, entao o nome do
arquivo precisa seguir o padrao PEP 427 ({nome}-{versao}-py3-none-any.whl). Por isso NAO
renomeamos o artefato: mantemos o nome canonico gerado pelo build (deterministico, pois
controlamos --name e a versao 0.0.0). O Terraform referencia esse mesmo nome.
"""

import argparse
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

# Versao fixa da distribuicao — define o nome canonico do wheel: {name}-{VERSION}-py3-none-any.whl
VERSION = "0.0.0"


def _handle_remove_readonly(func, path, exc_info):
    _ = exc_info
    os.chmod(path, stat.S_IWRITE)
    func(path)


def build_wheel(src: Path, dest: Path, name: str, package: str = "src") -> None:
    if dest.exists():
        shutil.rmtree(dest, onerror=_handle_remove_readonly)
    dest.mkdir(parents=True, exist_ok=True)

    src_package = src / package
    if not src_package.is_dir():
        raise FileNotFoundError(f"Pacote '{package}' nao encontrado em: {src_package}")

    with tempfile.TemporaryDirectory() as staging_str:
        staging = Path(staging_str)

        # Copia o pacote para o staging (sem __pycache__).
        shutil.copytree(
            src_package,
            staging / package,
            ignore=shutil.ignore_patterns("__pycache__"),
        )

        # pyproject.toml minimo declarando o pacote.
        (staging / "pyproject.toml").write_text(
            "[build-system]\n"
            'requires = ["setuptools>=61.0"]\n'
            'build-backend = "setuptools.build_meta"\n'
            "\n"
            "[project]\n"
            f'name = "{name}"\n'
            f'version = "{VERSION}"\n'
            "\n"
            "[tool.setuptools]\n"
            f'packages = ["{package}"]\n',
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

    # Mantem o nome canonico (PEP 427) exigido pelo `pip install` do Glue Python Shell.
    # O Terraform referencia o mesmo nome: {name}-{VERSION}-py3-none-any.whl
    expected = f"{name}-{VERSION}-py3-none-any.whl"
    if not (dest / expected).exists():
        raise RuntimeError(
            f"Wheel esperado '{expected}' nao encontrado; gerado: {[w.name for w in wheels]}"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--src", required=True, help="Diretorio do app (contem a pasta do pacote)")
    parser.add_argument("--dest", required=True, help="Diretorio de saida do wheel")
    parser.add_argument("--name", required=True, help="Nome da distribuicao do wheel")
    parser.add_argument("--package", default="src", help="Nome do pacote Python dentro de --src (default: src)")
    args = parser.parse_args()

    build_wheel(src=Path(args.src), dest=Path(args.dest), name=args.name, package=args.package)


if __name__ == "__main__":
    main()
