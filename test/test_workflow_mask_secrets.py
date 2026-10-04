"""Guarda do workflow de backfill: os segredos do Secrets Manager são mascarados no Actions.

O repositório é público e o log do Actions também; a chave do TMDB viaja como parâmetro de query e
a mensagem de qualquer exceção do requests a carrega (vazou num run de backfill de dev). O código
já mascara na origem (shared_utils.secret_redaction); este teste trava a última camada, o
`::add-mask::` com os valores do secret, que precisa rodar ANTES do step do backfill.
"""

from pathlib import Path

import yaml

_WORKFLOW = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "backfill.yml"


def _steps() -> list[dict]:
    workflow = yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))
    return next(iter(workflow["jobs"].values()))["steps"]


def _indice(steps: list[dict], prefixo: str) -> int:
    return next(i for i, step in enumerate(steps) if step.get("name", "").startswith(prefixo))


class TestBackfillMascaraSegredos:
    def test_step_de_mascara_roda_antes_do_backfill_e_depois_das_credenciais_aws(self):
        steps = _steps()
        assert _indice(steps, "Configure AWS credentials") < _indice(steps, "Mask secrets") < _indice(steps, "Run backfill")

    def test_step_de_mascara_le_o_secret_unificado_e_emite_add_mask(self):
        steps = _steps()
        step = steps[_indice(steps, "Mask secrets")]
        assert "FILMBOT_SECRET_ARN" in step["env"]
        assert "secretsmanager get-secret-value" in step["run"]
        assert "::add-mask::" in step["run"]

    def test_add_mask_nao_roda_no_step_do_backfill(self):
        """O stdout do step do backfill passa pelo `tee` para $LOG_FILE (de onde sai o step
        summary): o comando ::add-mask:: ali gravaria o segredo no arquivo."""
        steps = _steps()
        assert "::add-mask::" not in steps[_indice(steps, "Run backfill")]["run"]

    def test_step_summary_sanitiza_api_key_das_linhas_de_erro(self):
        steps = _steps()
        run = steps[_indice(steps, "Run backfill")]["run"]
        assert "sed -E 's/(api_key=)" in run
