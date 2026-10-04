"""Garante que todo requirements.txt que instala o litellm também declara o tenacity.

O litellm só importa o tenacity quando precisa retentar (num_retries) e não o declara como
dependência: sem ele, todo erro transitório (429/timeout/finish_reason=error) vira falha na hora,
sem nenhum dos retries configurados — foi o que apareceu em 69 falhas de detecção de idioma no
backfill de dev ("tenacity import failed please run `pip install tenacity`").
"""

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent

# Pacotes que já trazem o tenacity como dependência (o lightsail_ia o recebe via streamlit).
_TRAZEM_TENACITY = {"tenacity", "streamlit"}


def _pacotes(requirements: Path) -> set[str]:
    nomes = set()
    for linha in requirements.read_text(encoding="utf-8").splitlines():
        linha = linha.split("#", 1)[0].strip()
        if linha:
            nomes.add(re.split(r"[=<>!~\[;\s]", linha, maxsplit=1)[0].lower())
    return nomes


def _requirements_com_litellm() -> list[Path]:
    candidatos = [*_REPO_ROOT.glob("app/*/requirements.txt"), _REPO_ROOT / "scripts" / "requirements_backfill.txt"]
    return sorted(p for p in candidatos if "litellm" in _pacotes(p))


class TestTenacityComLitellm:
    def test_encontra_os_requirements_que_usam_litellm(self):
        """Trava o glob: se a estrutura de pastas mudar e nada for encontrado, o teste abaixo
        passaria vazio sem proteger nada."""
        nomes = {p.parent.name for p in _requirements_com_litellm()}
        assert {"glue_details", "glue_etl", "scripts"} <= nomes

    @pytest.mark.parametrize(
        "requirements",
        _requirements_com_litellm(),
        ids=lambda p: str(p.relative_to(_REPO_ROOT)).replace("\\", "/"),
    )
    def test_requirements_com_litellm_declara_tenacity(self, requirements):
        assert _pacotes(requirements) & _TRAZEM_TENACITY, (
            f"{requirements.relative_to(_REPO_ROOT)} instala o litellm mas não o tenacity: "
            "sem ele os retries (num_retries) do litellm nunca acontecem."
        )
