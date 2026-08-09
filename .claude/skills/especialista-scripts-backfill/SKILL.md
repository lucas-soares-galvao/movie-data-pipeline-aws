---
name: especialista-scripts-backfill
description: Especialista no mecanismo de backfill manual em `scripts/` (checkpoint em S3, exit code 75, retomada automática) e no racional de design por trás dos 8 scripts + `backfill_shared.py`. Use ao criar um script de backfill novo, alterar checkpoint/retry, decidir se um script deve abortar no primeiro erro ou continuar (fire-and-forget vs. soft-fail), revisar o guard de custo do `TRANSLATE_PROVIDER`, encadear scripts existentes (ver `backfill_historico.py`), entender o contrato entre um script e `.github/workflows/05_backfill.yml` (inclui a chamada local ao Glue AGG via `backfill_shared.trigger_agg_locally`, uma única vez por script, ver `trigger_agg`/`backfill_historico.py`), ou a notificação de sucesso por e-mail (`backfill_shared.notify_backfill_success`). Cobre a granularidade de `unit_id` por script, os 3 padrões de tratamento de erro já em uso, e o gap entre "unidade marcada como concluída" e "unidade realmente bem-sucedida" em `backfill_data_quality.py`.
---

# Especialista em Scripts de Backfill

## Papel

Você avalia todo script de backfill pela pergunta: **"se isto for interrompido no meio (token expirado, falha de
rede, um Ctrl+C acidental) e disparado de novo com o mesmo range de anos, ele retoma de onde parou sem reprocessar
nem perder trabalho — e sem mentir sobre o que já terminou?"**. Os 8 scripts de `scripts/` + `backfill_shared.py`
existem para reprocessar até 26 anos de histórico (2000–atual) dentro de sessões AWS de 1h (OIDC) — o checkpoint em
S3 e o exit code 75 são o mecanismo que torna isso seguro de rodar por horas sem supervisão constante. Nenhum dos 8
scripts invoca a Lambda API hoje — todos rodam a coleta TMDB e a transformação equivalente ao Glue ETL/Glue Details/Glue
AGG diretamente no processo do script (ou, no caso de `backfill_historico.py`, chamam o `main()` de dois outros scripts
que já rodam essa lógica em processo — ver "Práticas já aplicadas"), mantendo apenas o Glue Data Quality como job real
— o único caso que não pode ser internalizado, porque depende do motor `awsgluedq`, exclusivo do runtime Spark do Glue.
`scripts/` também é estruturalmente diferente de `app/<modulo>/src/utils.py` +
`main.py` (cada script concentra `main()` e helpers privados no próprio arquivo, sem pasta `src/`) — decisão
deliberada, não descuido: são runbooks de operação manual fora do gate de cobertura de 95%, não código do pipeline
deployado. Esta skill não descreve o que cada script faz linha a linha (isso é `scripts/scripts.md`) nem os testes
(`test/scripts/scripts_tests.md`) — foca no racional de design: por que a unidade de checkpoint é o que é, por que
existem 3 padrões diferentes de tratamento de erro entre os 8 scripts, e o que um script novo precisa reaproveitar
de `backfill_shared.py` para não reintroduzir um bug já corrigido.

## Fontes de verdade (ler antes de agir)

| O quê | Onde |
|---|---|
| Descrição de cada um dos 8 scripts, variáveis de ambiente, como executar (workflow ou local) | `scripts/scripts.md` |
| Casos de teste por script, os 4 bugs reais que motivaram a suíte | `test/scripts/scripts_tests.md` |
| Mecânica YAML do workflow, loop de retry, renovação de credencial via OIDC | `especialista-workflows-github`, `.github/workflows/05_backfill.yml` |
| Funções reaproveitadas dos jobs reais (`collect_discover_data` em `app/lambda_api/src/utils.py`; `read_from_sor`/`write_parquet_to_sot` em `app/glue_etl/src/utils.py`; `run_details_and_watch_providers_for_year` em `app/glue_details/src/utils.py`; `run_athena_query`/`write_parquet_to_spec` em `app/glue_agg/src/utils.py`, via `backfill_shared.trigger_agg_locally`) | `especialista-engenharia-dados-app` |
| Padrões de mock específicos de `test/scripts/` (parametrização `ExpiredTokenException`/`ExpiredToken`) | `especialista-testes-app` |
| Guard de custo do AWS Translate como decisão de FinOps | `especialista-finops-aws` |

## Práticas já aplicadas — preservar

- **`unit_id` é uma chave textual `"tipo:ano"` ou `"tabela:ano"` guardada num `set`**, nunca um índice numérico ou
  um booleano por ano — permite granularidade sub-ano (ex.: `movie:2020` concluído, `tv:2020` pendente) sem
  estrutura de dados adicional. Ver `load_checkpoint` (`scripts/backfill_shared.py:272-310`) e o filtro
  `pendentes = [u for u in unidades if f"{u[0]}:{u[1]}" not in completed]` em `scripts/backfill_discover.py:151`.
- **A granularidade do `unit_id` varia por script deliberadamente, não por descuido**: `backfill_discover.py`
  (`:95`), `backfill_enriquecimento.py` (`:147`) e `backfill_traducao.py` usam `tipo:ano` (a chamada real é por
  `media_type`), enquanto `backfill_data_quality.py` (`scripts/backfill_data_quality.py:128`:
  `f"{table_name}:{year}"`) e `backfill_rename_colunas.py` (`scripts/backfill_rename_colunas.py:203`) usam
  `tabela:ano`, porque essas duas iteram sobre uma lista de tabelas específicas (discover/details/watch_providers,
  movie e tv juntos), não sobre "tipo". Um script novo deve escolher a chave que corresponde à unidade de trabalho
  real que ele dispara — não copiar `tipo:ano` por padrão.
- **`backfill_historico.py` usa uma terceira granularidade de `unit_id`: nome de estágio** (`"discover"`,
  `"enriquecimento"`), nem `tipo:ano` nem `tabela:ano` — porque a unidade de trabalho real desse script não é uma
  chamada TMDB nem uma tabela, é "rodar `backfill_discover.py` até o fim sem falhas" e "rodar
  `backfill_enriquecimento.py` até o fim sem falhas". É um checkpoint de nível mais alto, por cima dos checkpoints
  por ano/tipo que os dois scripts chamados já mantêm sozinhos (`TABLE_GROUP="discover"` e
  `TABLE_GROUP="detalhes_e_providers"`) — existe só para não redigitar um estágio inteiro que já terminou sem
  falhas (e por isso já limpou o próprio checkpoint) quando o estágio seguinte é interrompido por token expirado.
  Um script que encadeia outros scripts existentes deve seguir esse padrão — checkpoint próprio com unidade =
  "nome do que está sendo encadeado" — em vez de reimplementar a lógica interna de cada um.
- **`save_checkpoint` é chamado a cada unidade concluída dentro do loop** (ex.
  `scripts/backfill_discover.py:203`, `scripts/backfill_data_quality.py:136`), nunca uma vez só no fim — grava no
  S3 uma vez por unidade (custo desprezível, poucas dezenas de `PutObject` por backfill) para que uma interrupção a
  qualquer momento perca no máximo a unidade em andamento, não o batch inteiro.
- **`clear_checkpoint` (`scripts/backfill_shared.py:331-339`) só é chamado quando o backfill termina sem falhas
  pendentes**: `backfill_discover.py:228` e `backfill_enriquecimento.py:232` só chamam no ramo sem `failures`,
  preservando o checkpoint parcial quando sobra alguma unidade que falhou (padrão 2 abaixo).
- **`load_checkpoint` ignora — não apaga — um checkpoint cujo `start_year`/`end_year` salvos não batem com o range
  do run atual** (`scripts/backfill_shared.py:300-306`) — protege contra reaproveitar por engano o progresso de um
  backfill de outro intervalo de anos, mas preserva o arquivo antigo, caso o operador tenha trocado o range por
  engano e queira voltar.
- **Exit code 75 (`RETRYABLE_EXIT_CODE`) é um contrato explícito entre script e workflow**: `run_with_retry_exit`
  (`scripts/backfill_shared.py:190-205`) traduz qualquer `ClientError` de token expirado nesse código; o loop bash
  em `.github/workflows/05_backfill.yml:201-222` é o único lugar que interpreta esse número — reconhece 75 como
  "renovar credencial e tentar de novo" e qualquer outro código `!= 0` como falha real (`exit $codigo`, sem retry).
  Um script novo que capture uma exceção e chame `sys.exit` com outro número quebraria esse contrato
  silenciosamente. `backfill_referencias.py` e `backfill_changes.py` são os únicos scripts sem esse bloco — nenhum
  dos dois itera por ano nem grava checkpoint (não dependem de `BACKFILL_START_YEAR`/`BACKFILL_END_YEAR`), então não
  há progresso a retomar.
- **`is_expired_token_error` reconhece dois códigos de erro distintos para a mesma causa raiz**
  (`scripts/backfill_shared.py:49-54, 227-239`): `ExpiredTokenException` (STS — Glue, Athena, Secrets Manager) e
  `ExpiredToken` (S3 — `ListObjectsV2`/`get_object`/`put_object`/`delete_object`) — correção de um bug real de
  produção (bug #4 em `test/scripts/scripts_tests.md`) em que só o primeiro código era reconhecido e um backfill de
  tradução caiu sem acionar o retry automático.
- **`apply_translate_cost_guard` (`scripts/backfill_shared.py:87-114`) rebaixa `TRANSLATE_PROVIDER=aws` para
  `google` automaticamente quando o intervalo de anos pedido é maior que 1** — proteção contra o operador esquecer
  de voltar para `google` (grátis) depois de testar `aws` (pago por caractere) num intervalo curto, antes de
  disparar um backfill do catálogo histórico inteiro. Chamado explicitamente pelos 3 scripts que iteram por ano e
  dependem de tradução/detecção de idioma: `backfill_discover.py`, `backfill_enriquecimento.py:129-131` e
  `backfill_traducao.py` — não existe mais um wrapper comum tipo `build_base_payloads` (removido junto com
  `invoke_lambda_sync`, ver histórico do módulo); cada script chama o guard diretamente antes de resolver
  `translate_fn`/`detect_fn`.
- **3 padrões de tratamento de erro coexistem deliberadamente**, cada um adequado ao tipo de chamada AWS por trás:
  1. **Abortar no primeiro erro** (`backfill_traducao.py`, `backfill_rename_colunas.py`, `backfill_referencias.py`):
     qualquer exceção não tratada como token expirado propaga até o processo, que sai com código `!= 0` e
     traceback. Faz sentido quando a unidade de trabalho é pequena/idempotente e uma falha indica um problema que
     provavelmente se repetirá nas próximas unidades. Em `backfill_referencias.py`, uma falha em
     `collect_genre_data`/`collect_configuration_data` (ou na escrita Parquet equivalente ao Glue ETL) propaga
     direto e aborta o script — só `collect_watch_providers_ref` tem tratamento especial (`HTTPError` capturado e
     ignorado, réplica do mesmo `try/except` de `app/lambda_api/main.py`), não os 3 padrões descritos aqui.
  2. **Soft-fail-continue** (`backfill_discover.py:186-213`, `backfill_enriquecimento.py:150-182`,
     `backfill_changes.py`): cada unidade roda dentro de um `try/except` que distingue token expirado (propaga,
     para o `run_with_retry_exit` traduzir em exit 75) de qualquer outra exceção (loga o erro, adiciona a unidade à
     lista `failures` e continua para a próxima) — só marca `completed` (e só salva checkpoint) no ramo de sucesso.
     O checkpoint fica permanentemente incompleto até um re-run, e o Glue Data Quality (disparado uma vez ao final,
     não por unidade, nesses 3 scripts) só roda se `failures` estiver vazia.
  3. **Fire-and-forget** (`backfill_data_quality.py:122-144`): dispara `start_job_run` de forma assíncrona e marca
     a unidade como `completed` (e salva checkpoint) imediatamente após o disparo ter sido aceito pela API — sem
     nunca chamar `get_job_run` para confirmar que o job de fato terminou com sucesso. "Concluído" aqui significa
     "submetido", não "validado" — e `clear_checkpoint` roda incondicionalmente ao final (`:144`), diferente do
     padrão 2.
- **O Glue AGG roda em processo, dentro de cada script, uma única vez, via `backfill_shared.trigger_agg_locally`**
  (chamada em todo script exceto `backfill_data_quality.py`, que não escreve dado novo) — não mais via
  `aws glue start-job-run` centralizado no workflow. Viável porque `app/glue_agg/src/utils.py` é Python puro
  (awswrangler + pandas, sem Spark/GlueContext) — diferente do Glue Data Quality. A chamada é síncrona (a query
  Athena e a escrita Parquet já bloqueiam até terminar dentro do `awswrangler`), então não precisa de polling.
  **Ponto de chamada**: sempre imediatamente ANTES de `clear_checkpoint`, nunca depois — se `trigger_agg_locally`
  propagar token expirado, `run_with_retry_exit` traduz em exit 75 e o script inteiro é re-executado; se o
  checkpoint já tivesse sido limpo, a reexecução reprocessaria todas as unidades do zero só para retentar o AGG.
  Chamando antes, uma reexecução por token expirado encontra `pendentes=[]` (checkpoint intacto) e vai direto para
  o AGG de novo. **Garantia de "exatamente uma vez"**: como esse ponto só é alcançado uma vez por execução
  *bem-sucedida* do processo (tentativas que falham com exit 75 nunca chegam lá), a garantia que antes vinha de o
  disparo estar fora do loop de retry do bash agora vem da posição da chamada dentro de `main()` — mesmo efeito,
  mecanismo diferente. **`backfill_discover.py`/`backfill_enriquecimento.py` aceitam `trigger_agg: bool = True`**
  em `main()`, usado por `backfill_historico.py` (que chama os dois com `trigger_agg=False`) para disparar o AGG
  uma única vez, ele mesmo, depois que os dois estágios terminam sem pendências — evita 2 disparos por execução de
  `historico` (a query de unificação é cara, CTAS sobre o catálogo inteiro). Uma falha na chamada é capturada e
  logada como `ERROR` (mesmo padrão soft-fail já usado por unidade em discover/enriquecimento/changes) — não
  derruba um backfill que já terminou com sucesso; o trigger agendado (`aws_glue_trigger.agg_weekly`,
  sábado/domingo 08:00 BRT) e o alarme SNS dedicado (`aws_cloudwatch_event_rule.glue_agg_failed`,
  `infra/cloudwatch_glue_alarms.tf`) continuam cobrindo o caso. Token expirado propaga normalmente.
- **Notificação de sucesso via `backfill_shared.notify_backfill_success`** — publicação SNS direta por
  código (boto3), sem EventBridge no meio, mesmo racional do tópico de métricas do Glue Data Quality
  (`notify_failed_outcomes` em `app/glue_data_quality/src/utils.py`): não existe um "Job State Change"
  nativo para um processo Python rodando fora do Glue. Chamada no mesmo ponto de código que já
  representa "sucesso total" em cada script — regra prática: se o script já chama `clear_checkpoint`
  ou `trigger_agg_locally` sem exceção, é ali que a notificação também deve ir; nunca antes de um
  `return` antecipado por falha soft (`backfill_discover.py`/`backfill_enriquecimento.py`/
  `backfill_changes.py`/`backfill_historico.py`) nem depois de um ponto que uma exceção não tratada já
  teria abortado (padrão 1 acima). **Nunca propaga exceção** (nem token expirado) — diferente de
  `trigger_agg_locally`, roda depois do `clear_checkpoint`, então deixar propagar forçaria
  `run_with_retry_exit` a reprocessar o backfill inteiro só por uma falha de observabilidade; e o ARN do
  tópico (`SNS_TOPIC_ARN_BACKFILL_SUCCESS`) é lido como opcional (`os.environ.get`, não `require_env`)
  pelo mesmo motivo — a ausência da variável não pode abortar um backfill já concluído. **Suprimida
  junto com `trigger_agg=False`** em `backfill_discover.py`/`backfill_enriquecimento.py`: quando
  `backfill_historico.py` os encadeia, só ele notifica ao final dos dois estágios, não cada um
  individualmente — evita 3 e-mails redundantes por execução de `historico`, mesmo racional já usado
  para suprimir o disparo duplicado do Glue AGG.
- **O step summary também expõe o resumo real do próprio backfill, extraído do log via `grep`**: a saída do
  `executar_script` é gravada em `$RUNNER_TEMP/backfill_output.log` via `tee` (com
  `codigo=${PIPESTATUS[0]}`, não `$?`, para capturar o exit code do script e não do `tee`). Isso existe porque
  `codigo -eq 0` (a condição que já existia para decidir "backfill terminou") **não implica que toda unidade teve
  sucesso** para os 5 scripts com tratamento de erro não-abortante (padrões 2 e 3 acima, incluindo
  `backfill_historico.py`, que herda o soft-fail-continue dos dois scripts que encadeia): se sobrar alguma linha
  ` ERROR ` no log (mesmo formato em todos os 8 scripts, ver `backfill_shared.py:58-63`; `%(asctime)s` sai em
  horário de São Paulo, `DD/MM/YYYY HH:MM:SS`, via `Formatter.converter`/`datefmt` customizados, também em
  `backfill_shared.py`), o step summary mostra
  "Falhas parciais registradas" com as linhas encontradas, mesmo o job do Actions terminando verde. Um script novo
  não precisa fazer nada especial para isso funcionar — só logar `logger.error` normalmente nos casos de falha soft
  (como já fazem os padrões 2 e 3).

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

- **Script de backfill novo**: sempre reaproveitar `require_env`, `setup_logging`, o padrão `_start_glue_job`/
  `_wait_for_job` (ou `trigger_glue_job` fire-and-forget, conforme o caso), `read_year_range` e o bloco
  `if __name__ == "__main__": shared.run_with_retry_exit(main)` — nunca reimplementar retry/exit code do zero. Se o
  script precisar coletar dados do TMDB ou transformar SOR→SOT, reaproveitar as funções puras que a Lambda/Glue ETL
  já usam (`app/lambda_api/src/utils.py`, `app/glue_etl/src/utils.py`) em vez de invocar esses recursos como job —
  nenhum script novo deve voltar a depender da Lambda API.
- **Script que encadeia scripts existentes** (ex.: `backfill_historico.py` encadeando
  `backfill_discover.py` + `backfill_enriquecimento.py`): chamar o `main()` de cada um diretamente no processo
  (nunca `subprocess`) — preserva o retry de exit code 75 e o checkpoint interno de cada um sem nenhuma mudança
  neles. Não reimplementar a lógica que já existe dentro dos scripts encadeados. Se algum deles não expõe hoje um
  jeito de saber se terminou sem falhas pendentes, adicionar um retorno `bool` mínimo (`return not failures`) em vez
  de inferir isso por efeito colateral (ex.: checar se o checkpoint interno foi limpo — ambíguo quando zero unidades
  tiveram sucesso). Manter um checkpoint próprio de nível mais alto (unidade = nome do estágio, não `tipo:ano`) para
  não redigitar um estágio já concluído numa retomada.
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
  `apply_translate_cost_guard` explicitamente antes de resolver `translate_fn`/`detect_fn` — não assumir que o
  operador vai lembrar de usar `"google"` para backfills longos.
- **Script de backfill novo deve chamar `shared.notify_backfill_success(table_group, summary)`** no mesmo ponto em
  que já considera o backfill "sucesso total" (junto de `clear_checkpoint`/`trigger_agg_locally`, nunca antes de uma
  falha propagar ou de um `return` antecipado) — não reimplementar publicação SNS própria nem inventar um tópico
  novo. Se o script encadear outro que aceita `trigger_agg: bool`, replicar o mesmo gating para a notificação
  (suprimir no script encadeado, notificar uma única vez no orquestrador).
