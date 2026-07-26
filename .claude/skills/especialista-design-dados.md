---
name: especialista-design-dados
description: Especialista em decisões de design de dados que atravessam os jobs Glue (glue_etl, glue_details, glue_agg, glue_data_quality) — particionamento, modo de escrita/idempotência (overwrite vs. overwrite_partitions vs. read-merge-write manual), formato de arquivo por camada (JSON no SOR, Parquet no SOT/SPEC/DQ) e processamento incremental/delta. Use ao escolher partition_cols/mode para uma tabela nova ou alterada, ao decidir se uma escrita precisa de merge manual antes do wr.s3.to_parquet, ao investigar por que rodar um job duas vezes não duplica dados, ao desenhar a lógica que define "o que já foi processado" (delta), ou ao avaliar o impacto de uma mudança de schema numa tabela existente. Não cobre onde o código mora por serviço AWS (especialista-engenharia-dados-app.md) nem alarmes/regras DQDL de validação de qualidade (especialista-observabilidade-qualidade-dados.md).
---

# Especialista em Design de Dados — Particionamento, Idempotência e Formato

## Papel

Você avalia toda tabela nova ou alterada em `app/` pela pergunta: **"se este job rodar duas vezes seguidas com o
mesmo input — ou for interrompido no meio —, o resultado final é o mesmo: sem duplicar registro, sem perder
histórico de partições não tocadas, e sem deixar o Glue Catalog apontando para um arquivo que não existe mais?"**
Isso cobre quatro decisões que atravessam os quatro jobs Glue do pipeline (`glue_etl`, `glue_details`, `glue_agg`,
`glue_data_quality`) e que nenhuma skill hoje trata como tema único: **particionamento** (qual coluna, e por quê),
**modo de escrita/idempotência** (`overwrite` vs. `overwrite_partitions` vs. o padrão manual de read-merge-write que
antecede a chamada do awswrangler), **formato de arquivo por camada** (JSON no SOR, Parquet no SOT/SPEC/DQ), e
**processamento incremental/delta** (como cada job decide o que já foi processado e o que falta). Schema evolution
é tratada aqui como lacuna, não como prática resolvida — hoje só existe um caso real, resolvido por script de
runbook manual fora de `app/`.

## Fontes de verdade (ler antes de agir)

Esta skill cobre a decisão de design; não repete onde o código mora nem como a qualidade é validada:

| O quê | Onde |
|---|---|
| Onde mora cada função por serviço AWS (Lambda/Glue/Lightsail), reuso de `shared_utils` | `.claude/skills/especialista-engenharia-dados-app.md` |
| Alarmes CloudWatch, tópicos SNS, regras DQDL, guard estrutural pré-escrita | `.claude/skills/especialista-observabilidade-qualidade-dados.md` |
| Qual serviço AWS usar para uma necessidade nova (custo x volume x complexidade) | `.claude/skills/especialista-arquitetura-aws.md` |
| Custo x benefício dos recursos já escolhidos (lifecycle S3, DPU Glue) | `.claude/skills/especialista-finops-aws.md` |
| Arquitetura funcional/fluxo ponta a ponta, camadas S3, tabelas do Glue Catalog | `.claude/skills/projeto-filmes-aws.md` |
| Racional do único caso de schema evolution do projeto (rename de coluna via runbook) | `scripts/backfill_rename_colunas.py`, `.claude/skills/especialista-scripts-backfill.md` |

## Práticas já aplicadas — preservar

- **Três estratégias de particionamento coexistem, cada uma alinhada à unidade de processamento do job, não copiadas
  por padrão**: `partition_cols=["year"]` para tabelas que escalam por ano e são processadas por `YEAR`/`END_YEAR`
  (`glue_etl` discover — `app/glue_etl/main.py:29`; `glue_details` details/watch_providers —
  `app/glue_details/src/utils.py:921,993,1201`); `partition_cols=None` para tabelas de referência pequenas sem
  escala por ano (`genre`/`configuration`/`watch_providers_ref`/`now_playing` — `app/glue_etl/main.py:30-33`);
  `partition_cols=["media_type", "year"]` (dois níveis) só em `glue_agg`, porque a tabela SPEC precisa separar
  filme/série além do ano (`app/glue_agg/src/utils.py:150`); `partition_cols=["source_table", "year"]` em
  `glue_data_quality`, com `year="sem_ano"` como valor fixo para tabelas sem partição por ano — evita o erro do
  Athena "partition value count must match partition column count" ao misturar partições de 1 e 2 níveis
  (`app/glue_data_quality/src/utils.py:254-259,274`).
- **`year` vem sempre de `release_date`/`first_air_date`** (`app/glue_details/src/utils.py:589,604`), nunca da data
  de processamento — alinha a unidade de I/O (partição) com a unidade de negócio (ano de lançamento), permitindo
  `overwrite_partitions` afetar só o(s) ano(s) tocado(s) e `push_down_predicate` no DQ
  (`app/glue_data_quality/src/utils.py:104-114`, comentado como otimização de custo — evita ler partições que não
  mudaram).
- **`overwrite_partitions` é o modo default para escrita incremental**, usado em `glue_etl` discover
  (`app/glue_etl/main.py:29`), `glue_details` details/watch_providers
  (`app/glue_details/src/utils.py:922,994,1202`) e `glue_data_quality`
  (`app/glue_data_quality/src/utils.py:275`) — substitui só a(s) partição(ões) tocada(s), preservando anos
  anteriores intactos. `overwrite` total só aparece em tabelas de referência sem partição (`glue_etl` genre/
  configuration/watch_providers_ref/now_playing) e em `glue_agg` — nesse último por um motivo diferente de volume:
  comentário explícito em `app/glue_agg/src/utils.py:121-125` — `overwrite_partitions` pode deixar o Catalog
  apontando para arquivos antigos deletados se a atualização falhar parcialmente; como a tabela SPEC é sempre
  recalculada por completo, a escolha prioriza consistência do Catalog em caso de falha parcial, não volume de
  dados. **`mode="append"` nunca é usado em lugar nenhum do projeto** — toda escrita é substituição total ou por
  partição, nunca acréscimo cego.
- **Padrão read-merge-write manual precede `overwrite_partitions` sempre que a escrita é parcial** (só um subconjunto
  de IDs da partição, não a partição inteira): `collect_and_write_details`
  (`app/glue_details/src/utils.py:864-909`) lê a partição existente antes de escrever, separa
  `df_existing_keep` (fora do delta) de `df_existing_delta` (dentro do delta, reaproveitado como cache de tradução),
  concatena `df_existing_keep + df_novo` e aplica `drop_duplicates(subset=["id"], keep="last")` — comentário
  explícito nas linhas 903-906: "evita perder registros ao usar overwrite_partitions". `collect_and_write_watch_providers`
  (`app/glue_details/src/utils.py:1174-1190`) segue o mesmo padrão: remove do `df_existing` os IDs que serão
  atualizados antes de concatenar com o novo. Sem esse merge, `overwrite_partitions` sozinho apagaria da partição
  todo registro não incluído no DataFrame do run atual.
- **`_repair_partition_duplicates` e as três funções `repair_*` são a segunda camada de defesa**, não o mecanismo
  principal (`app/glue_details/src/utils.py:935-1126`): rodam só no final do ciclo (`year == end_year`), ordenam por
  uma coluna de recência (`processed_date` para details, `popularity` para discover) e aplicam
  `drop_duplicates(keep="last")`, só regravando se `before != after` — proteção redundante contra duplicatas que
  escaparam do merge acima (ex.: execuções concorrentes do mesmo ano).
- **`glue_etl` discover é a exceção deliberada ao padrão read-merge-write**: `write_parquet_to_sot`
  (`app/glue_etl/src/utils.py:338-370`) não faz merge — recebe `partition_cols`/`mode` como parâmetros vindos de
  `_TABLE_CONFIG` e grava direto. Isso é seguro porque `read_from_sor` já reconstrói a partição inteira a partir do
  SOR daquele ano e aplica `drop_duplicates(subset=["id"])` antes de gravar (`app/glue_etl/src/utils.py:304`) — o
  SOR de um ano é sempre uma coleta completa daquele ano, então "substituir a partição inteira" nunca perde dado,
  diferente de `glue_details`, onde cada run processa só um subconjunto de IDs da partição.
- **Formato por camada**: SOR é sempre JSON — `wr.s3.read_json` para arquivos-array (discover/now_playing,
  `app/glue_etl/src/utils.py:302,310`) e `_read_json_from_s3` (boto3 + `json.loads`) para arquivo único
  (`watch_providers_ref`/`genre`/`configuration`), porque "o wrangler pode ter comportamento inesperado" nesse caso
  — comentário explícito em `app/glue_etl/src/utils.py:313-315`. SOT/SPEC/DQ são sempre Parquet via
  `wr.s3.to_parquet(..., dataset=True, database=..., table=...)`, que grava e atualiza o Glue Catalog na mesma
  chamada (`.claude/skills/projeto-filmes-aws.md:65-68`).
- **Delta é calculado por janela mensal, não por partição isolada**: `fetch_existing_ids_from_details`
  (`app/glue_details/src/utils.py:152-198`) considera "já processado" um ID cujo `processed_date` é deste mês, **em
  qualquer partição `year`** — não só a partição do `year` sendo processado agora — porque o `release_date` de um
  título pode mudar de ano entre execuções, e comparar só a partição atual reprocessaria (e sobrescreveria em
  paralelo) o mesmo ID em duas partições diferentes (comentário `:160-163`). IDs de meses anteriores são
  considerados "stale" e voltam a ser buscados no mês seguinte. `fetch_ids_stale_watch_providers`
  (`app/glue_details/src/utils.py:201-253`) usa um delta separado (LEFT JOIN discover × watch_providers) para o
  mesmo motivo: ID sem registro, `updated_date` nulo, ou desatualizado antes do mês corrente. O modo changes
  (`resolve_years_for_changed_ids`/`process_changed_ids`, `app/glue_details/src/utils.py:1250-1405`) é um terceiro
  tipo de delta, orientado por evento (TMDB Changes API) em vez de janela de tempo — cruza IDs mudados com o
  discover para achar o `year`, descartando IDs que nunca entraram no catálogo via `/discover` (preserva a
  curadoria do pipeline).

## Lacunas encontradas — avaliar risco x esforço antes de agir

- **Schema evolution não tem mecanismo genérico em `app/`** — o único caso real (rename
  `dt_processamento`/`dt_atualizacao` → `processed_date`/`updated_date`) foi resolvido inteiramente em
  `scripts/backfill_rename_colunas.py`, um runbook manual fora de `app/`: lê o schema físico real da partição,
  aplica coalesce da coluna nova sobre a antiga, dropa a antiga. Não existe em `app/` nenhuma função de
  `reindex` para colunas ausentes, validação de schema contra o Glue Catalog antes de escrever, ou biblioteca de
  contrato de schema (`pandera`/`great_expectations`). O único mecanismo parecido é `CAST(NULL AS <tipo>)` em
  `app/glue_agg/src/queries.py` para alinhar colunas entre movie/tv num `UNION ALL` — é alinhamento de tipos dentro
  de uma query, não schema evolution ao longo do tempo. Se uma mudança futura (campo novo do TMDB, tipo alterado)
  precisar de tratamento automático em vez de runbook manual, é trabalho de arquitetura novo, não ajuste pequeno —
  avaliar antes de propor.
- **Por que Parquet nas camadas SOT/SPEC/DQ nunca é explicado em comentário** — é conhecimento tácito do ecossistema
  Glue Catalog + Athena (colunar, compressão, schema tipado, particionamento nativo), correto e consistente em 100%
  dos casos, mas não documentado em lugar nenhum do código; alguém sem esse contexto de ecossistema não teria como
  inferir o "por quê" só lendo `app/`.
- **A razão pela qual `glue_etl` discover dispensa o merge manual que `glue_details` exige não está escrita em
  nenhum comentário único** — está implícita em dois arquivos diferentes (docstring de `app/glue_etl/main.py:4-6`
  e o `drop_duplicates` de `app/glue_etl/src/utils.py:304`). Um contribuidor lendo só `glue_details` (onde o merge é
  explicado em detalhe) pode concluir por engano que todo `overwrite_partitions` do projeto precisa de merge manual
  antes, e replicar o padrão sem necessidade em `glue_etl` — ou, o oposto, omitir o merge num job novo cuja escrita
  é parcial como `glue_details`, achando que `overwrite_partitions` sozinho basta.

## Regras práticas ao escrever/revisar mudança nova

- **Tabela nova**: escolher `partition_cols` pela unidade real de escala, não copiar `["year"]` por padrão — tabela
  de referência pequena e reescrita por completo a cada run usa `partition_cols=None` + `mode="overwrite"`; tabela
  que cresce por ano e é processada por `YEAR`/`END_YEAR` usa `["year"]`; tabela com mais de uma dimensão de corte
  (ex. `media_type`) usa múltiplas colunas.
- **Antes de usar `mode="overwrite_partitions"`, perguntar: este run escreve o subconjunto inteiro da partição, ou
  só parte dela (ex. só os IDs de um delta)?** Se só parte, replicar o padrão read-merge-write de
  `collect_and_write_details`/`collect_and_write_watch_providers` (ler partição existente → separar o que fica do
  que é sobrescrito → concatenar → `drop_duplicates(keep="last")`) antes de chamar `wr.s3.to_parquet` — nunca
  confiar só no `mode` do awswrangler para não perder registro.
- **`mode="overwrite"` total só se justifica quando a tabela é sempre recalculada por inteiro E a consistência do
  Glue Catalog em caso de falha parcial importa mais que preservar partições não tocadas** (caso `glue_agg` —
  `app/glue_agg/src/utils.py:121-125`) — não usar `overwrite` total só porque é mais simples de escrever.
- **Coluna nova numa tabela existente**: seguir o precedente de `scripts/backfill_rename_colunas.py` — ler o schema
  físico real da partição antes de migrar, nunca assumir que `wr.s3.to_parquet` detecta e evolui schema sozinho. Se
  a mudança afeta tabela histórica com anos já gravados, é backfill manual, não só alterar o código do job daqui
  para frente.
- **Lógica de delta nova**: se "processado" pode mudar de partição entre execuções (ex.: `release_date` mudando de
  ano), comparar contra a tabela inteira ou por janela de tempo (`processed_date >= date_trunc(...)`), nunca só
  contra a partição do run atual — o padrão de `fetch_existing_ids_from_details`
  (`app/glue_details/src/utils.py:152-198`) evita reprocessar/sobrescrever o mesmo ID em duas partições diferentes.
- **JSON só no SOR, Parquet em tudo depois dele**: não introduzir um formato novo numa camada existente sem
  justificar contra o padrão já em vigor (`.claude/skills/projeto-filmes-aws.md:65-68`).
