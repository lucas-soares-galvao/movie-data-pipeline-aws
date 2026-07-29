---
name: especialista-scripts-backfill
description: Especialista no mecanismo de backfill manual em `scripts/` (checkpoint em S3, exit code 75, retomada automática) e no racional de design por trás dos 6 scripts + `backfill_shared.py`. Use ao criar um script de backfill novo, alterar checkpoint/retry, decidir se um script deve abortar no primeiro erro ou continuar (fire-and-forget vs. soft-fail), revisar o guard de custo do `TRANSLATE_PROVIDER`, ou entender o contrato entre um script e `.github/workflows/05_backfill.yml`. Cobre a granularidade de `unit_id` por script, os 3 padrões de tratamento de erro já em uso, e o gap entre "unidade marcada como concluída" e "unidade realmente bem-sucedida" em `backfill_data_quality.py`.
---

# Especialista em Scripts de Backfill

## Papel

Você avalia todo script de backfill pela pergunta: **"se isto for interrompido no meio (token expirado, falha de
rede, um Ctrl+C acidental) e disparado de novo com o mesmo range de anos, ele retoma de onde parou sem reprocessar
nem perder trabalho — e sem mentir sobre o que já terminou?"**. Os 6 scripts de `scripts/` + `backfill_shared.py`
existem para reprocessar até 26 anos de histórico (2000–atual) através de recursos com timeout curto (Lambda 900s)
ou sessões AWS de 1h (OIDC) — o checkpoint em S3 e o exit code 75 são o mecanismo que torna isso seguro de rodar por
horas sem supervisão constante. `scripts/` também é estruturalmente diferente de `app/<modulo>/src/utils.py` +
`main.py` (cada script concentra `main()` e helpers privados no próprio arquivo, sem pasta `src/`) — decisão
deliberada, não descuido: são runbooks de operação manual fora do gate de cobertura de 95%, não código do pipeline
deployado. Esta skill não descreve o que cada script faz linha a linha (isso é `scripts/scripts.md`) nem os testes
(`test/scripts/scripts_tests.md`) — foca no racional de design: por que a unidade de checkpoint é o que é, por que
existem 3 padrões diferentes de tratamento de erro entre os 6 scripts, e o que um script novo precisa reaproveitar
de `backfill_shared.py` para não reintroduzir um bug já corrigido.

## Fontes de verdade (ler antes de agir)

| O quê | Onde |
|---|---|
| Descrição de cada um dos 6 scripts, variáveis de ambiente, como executar (workflow ou local) | `scripts/scripts.md` |
| Casos de teste por script, os 4 bugs reais que motivaram a suíte | `test/scripts/scripts_tests.md` |
| Mecânica YAML do workflow, loop de retry, renovação de credencial via OIDC | `especialista-workflows-github`, `.github/workflows/05_backfill.yml` |
| Payloads enviados à Lambda API e o que `app/lambda_api/main.py` de fato lê | `especialista-engenharia-dados-app` |
| Padrões de mock específicos de `test/scripts/` (parametrização `ExpiredTokenException`/`ExpiredToken`) | `especialista-testes-app` |
| Guard de custo do AWS Translate como decisão de FinOps | `especialista-finops-aws` |

## Práticas já aplicadas — preservar

- **`unit_id` é uma chave textual `"tipo:ano"` ou `"tabela:ano"` guardada num `set`**, nunca um índice numérico ou
  um booleano por ano — permite granularidade sub-ano (ex.: `movie:2020` concluído, `tv:2020` pendente) sem
  estrutura de dados adicional. Ver `load_checkpoint` (`scripts/backfill_shared.py:272-310`) e o filtro
  `pendentes = [u for u in unidades if f"{u[0]}:{u[1]}" not in completed]` em `scripts/backfill_historico.py:95`.
- **A granularidade do `unit_id` varia por script deliberadamente, não por descuido**: `backfill_historico.py`
  (`:95`), `backfill_enriquecimento.py` (`:147`) e `backfill_traducao.py` usam `tipo:ano` (a chamada real é por
  `media_type`), enquanto `backfill_data_quality.py` (`scripts/backfill_data_quality.py:128`:
  `f"{table_name}:{year}"`) e `backfill_rename_colunas.py` (`scripts/backfill_rename_colunas.py:203`) usam
  `tabela:ano`, porque essas duas iteram sobre uma lista de tabelas específicas (discover/details/watch_providers,
  movie e tv juntos), não sobre "tipo". Um script novo deve escolher a chave que corresponde à unidade de trabalho
  real que ele dispara — não copiar `tipo:ano` por padrão.
- **`save_checkpoint` é chamado a cada unidade concluída dentro do loop** (ex.
  `scripts/backfill_historico.py:103`, `scripts/backfill_data_quality.py:136`), nunca uma vez só no fim — grava no
  S3 uma vez por unidade (custo desprezível, poucas dezenas de `PutObject` por backfill) para que uma interrupção a
  qualquer momento perca no máximo a unidade em andamento, não o batch inteiro.
- **`clear_checkpoint` (`scripts/backfill_shared.py:331-339`) só é chamado quando o backfill termina sem falhas
  pendentes**: `backfill_historico.py:108` chama sempre, porque qualquer falha já teria abortado o processo antes
  (padrão 1 abaixo); `backfill_enriquecimento.py:175-182` só chama no ramo `else` (sem `failures`), preservando o
  checkpoint parcial quando sobra alguma unidade `FAILED`/`STOPPED`/`ERROR`/`TIMEOUT`.
- **`load_checkpoint` ignora — não apaga — um checkpoint cujo `start_year`/`end_year` salvos não batem com o range
  do run atual** (`scripts/backfill_shared.py:300-306`) — protege contra reaproveitar por engano o progresso de um
  backfill de outro intervalo de anos, mas preserva o arquivo antigo, caso o operador tenha trocado o range por
  engano e queira voltar.
- **Exit code 75 (`RETRYABLE_EXIT_CODE`) é um contrato explícito entre script e workflow**: `run_with_retry_exit`
  (`scripts/backfill_shared.py:190-205`) traduz qualquer `ClientError` de token expirado nesse código; o loop bash
  em `.github/workflows/05_backfill.yml:201-222` é o único lugar que interpreta esse número — reconhece 75 como
  "renovar credencial e tentar de novo" e qualquer outro código `!= 0` como falha real (`exit $codigo`, sem retry).
  Um script novo que capture uma exceção e chame `sys.exit` com outro número quebraria esse contrato
  silenciosamente. `backfill_referencias.py` é o único script sem esse bloco — não itera por ano, não grava
  checkpoint, então não há progresso a retomar.
- **`is_expired_token_error` reconhece dois códigos de erro distintos para a mesma causa raiz**
  (`scripts/backfill_shared.py:49-54, 227-239`): `ExpiredTokenException` (STS — Lambda/Glue) e `ExpiredToken` (S3 —
  `ListObjectsV2`/`get_object`/`put_object`/`delete_object`) — correção de um bug real de produção (bug #4 em
  `test/scripts/scripts_tests.md`) em que só o primeiro código era reconhecido e um backfill de tradução caiu sem
  acionar o retry automático.
- **`apply_translate_cost_guard` (`scripts/backfill_shared.py:100-127`) rebaixa `TRANSLATE_PROVIDER=aws` para
  `google` automaticamente quando o intervalo de anos pedido é maior que 1** — proteção contra o operador esquecer
  de voltar para `google` (grátis) depois de testar `aws` (pago por caractere) num intervalo curto, antes de
  disparar um backfill do catálogo histórico inteiro. Chamado tanto dentro de `build_base_payloads`
  (`scripts/backfill_shared.py:150-152`, usado por historico/referencias) quanto explicitamente por
  `backfill_enriquecimento.py:126-128` e `backfill_traducao.py` (que não passam por `build_base_payloads` para
  essa variável).
- **3 padrões de tratamento de erro coexistem deliberadamente**, cada um adequado ao tipo de chamada AWS por trás:
  1. **Abortar no primeiro erro** (`backfill_historico.py`, `backfill_traducao.py`, `backfill_rename_colunas.py`):
     `invoke_lambda_sync` levanta `RuntimeError` se a Lambda retornar `FunctionError`
     (`scripts/backfill_shared.py:94-95`); qualquer exceção não tratada como token expirado propaga até o
     processo, que sai com código `!= 0` e traceback. Faz sentido quando a chamada é síncrona e uma falha indica
     um problema que provavelmente se repetirá nas próximas unidades.
  2. **Soft-fail-continue** (`backfill_enriquecimento.py:150-182`): aguarda o Glue job terminar (`_wait_for_job`)
     e, se o estado final não for `SUCCEEDED`, loga o erro, adiciona a unidade à lista `failures` e continua para
     a próxima — só marca `completed` (e só salva checkpoint) no ramo de sucesso (`:167-168`). O checkpoint fica
     permanentemente incompleto até um re-run.
  3. **Fire-and-forget** (`backfill_data_quality.py:122-144`): dispara `start_job_run` de forma assíncrona e marca
     a unidade como `completed` (e salva checkpoint) imediatamente após o disparo ter sido aceito pela API — sem
     nunca chamar `get_job_run` para confirmar que o job de fato terminou com sucesso. "Concluído" aqui significa
     "submetido", não "validado" — e `clear_checkpoint` roda incondicionalmente ao final (`:144`), diferente do
     padrão 2.

## Lacunas encontradas — avaliar risco x esforço antes de agir

- **`backfill_data_quality.py` marca uma unidade como `completed` assim que `start_job_run` retorna com sucesso**
  (`scripts/backfill_data_quality.py:133-136`), sem nunca consultar `get_job_run` — se o job Glue Data Quality
  falhar depois de aceito, nem o checkpoint nem o log final ("N execuções submetidas") refletem isso; o operador só
  descobriria via alarme separado ou auditoria manual dos runs no console Glue. Diferente de
  `backfill_enriquecimento.py`, que espera e trata falha explicitamente. Alinhar os dois exigiria fazer
  `backfill_data_quality.py` esperar por até 60 runs em paralelo (`max_concurrent_runs=10`) — mudança de
  arquitetura, não um ajuste pequeno; avaliar se vale o custo antes de propor.
- **Nenhum teste em `test/scripts/` cobre esse gap "`completed` != validado" de `backfill_data_quality.py`** — os
  testes de contrato descritos em `scripts_tests.md` verificam o payload/argumentos enviados, não a semântica do
  checkpoint. Se decidir corrigir a lacuna acima, o teste que trava a regressão também não existe ainda.
- **`table_group` é texto livre repetido em 3 lugares sem validação cruzada automática**: a lista de `choices` do
  `workflow_dispatch` (`.github/workflows/05_backfill.yml:39-45`), o `case` do bash que resolve qual script rodar
  (`:167-174`), e o valor que cada script recebe via `TABLE_GROUP` (usado só como chave do checkpoint, nunca
  validado contra uma lista permitida dentro do próprio script Python). Adicionar um `table_group` novo sem
  atualizar os 3 lugares (mais `scripts/scripts.md`) resulta em falha silenciosa ou script executando com um
  `table_group` não intencional.

## Regras práticas ao escrever/revisar mudança nova

- **Script de backfill novo**: sempre reaproveitar `require_env`, `setup_logging`, `invoke_lambda_sync` ou o padrão
  `_start_glue_job`/`_wait_for_job` (conforme o serviço AWS), `read_year_range` e o bloco
  `if __name__ == "__main__": shared.run_with_retry_exit(main)` — nunca reimplementar retry/exit code do zero.
- **Se o script novo itera por ano**: usar `load_checkpoint`/`save_checkpoint`/`clear_checkpoint` de
  `backfill_shared.py`, escolhendo o `unit_id` que corresponde à unidade de trabalho real (`tipo:ano` se a chamada
  é por `media_type`; `tabela:ano` se é por tabela específica) — não copiar `tipo:ano` por padrão sem checar qual
  granularidade o script novo dispara de fato.
- **`save_checkpoint` a cada unidade concluída dentro do loop**, nunca em lote no fim — é o que garante que uma
  interrupção no meio perca o mínimo de progresso possível.
- **`clear_checkpoint` só no caminho sem falhas pendentes**; se o script tiver algum tipo de falha "soft" possível
  (job que pode terminar em estado != sucesso sem levantar exceção), seguir o padrão `failures`/soft-fail-continue
  de `backfill_enriquecimento.py` — não o fire-and-forget de `backfill_data_quality.py`, que é uma lacuna conhecida,
  não um modelo a replicar.
- **Qualquer `sys.exit` direto num script de backfill deve usar `shared.RETRYABLE_EXIT_CODE` (75) só para token
  expirado** — nunca reaproveitar esse número para outro tipo de erro, e nunca introduzir um exit code novo sem
  também atualizar o loop bash em `05_backfill.yml` que o interpreta.
- **`table_group` novo**: adicionar nas 3 pontas (choices do `workflow_dispatch`, `case` do bash, docstring do
  script) mais `scripts/scripts.md` no mesmo PR — nada valida a string em runtime hoje (ver "Lacunas encontradas").
- **Guard de custo de tradução**: se o script novo aceitar `TRANSLATE_PROVIDER` e depender de range de anos, chamar
  `apply_translate_cost_guard` explicitamente (ou via `build_base_payloads`, se aplicável) antes de montar
  qualquer payload/argumento — não assumir que o operador vai lembrar de usar `"google"` para backfills longos.
