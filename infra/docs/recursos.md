# Recursos AWS provisionados

## Armazenamento — S3 (`s3.tf`)

6 buckets com papéis distintos na arquitetura medalhão:

| Bucket | Nome (sem sufixo de ambiente) | Papel |
|---|---|---|
| SOR | `lsg-sa-east-1-bucket-sor` | Source of Record — dados brutos (JSON da TMDB) |
| SOT | `lsg-sa-east-1-bucket-sot` | Source of Truth — dados processados (Parquet) |
| SPEC | `lsg-sa-east-1-bucket-spec` | Specialized — tabela unificada para o app (Gold) |
| DQ | `lsg-sa-east-1-bucket-data-quality` | Resultados de validação de qualidade |
| AUX | `lsg-sa-east-1-bucket-aux` | Auxiliar — artefatos de código (zips, wheels) |
| TEMP | `lsg-sa-east-1-bucket-temp` | Temporário — resultados de queries Athena |

> Dentro dos buckets AUX, TEMP e SPEC, os objetos também são gravados sob um prefixo de chave `tmdb/` (scripts e wheels dos jobs Glue, resultados temporários do Athena, dados gravados pelo Glue AGG).

## Computação — Lambda (`lambda_api.tf`)

- Função Lambda `lambda-api-{env}` com timeout e memória configurados
- Pacote Python gerado por `infra/scripts/build_lambda_package.py` e enviado ao bucket AUX
- Variáveis de ambiente injetadas pelo Terraform (nomes de buckets, jobs, ARN do segredo)

## Computação — Glue Jobs (`glue_etl.tf`, `glue_details.tf`, `glue_agg.tf`, `glue_data_quality.tf`)

4 jobs Glue. Os jobs ETL, Details e AGG são do tipo **PythonShell** (Glue 3.9). O job Data Quality é do tipo **Spark (`glueetl`)** (Glue 5.0, 2 workers G.1X, execução FLEX) — exigido pela API `EvaluateDataQuality` da AWS. Cada job tem:
- Worker type e número de workers configurados por ambiente
- Wheel Python gerado por `infra/scripts/build_glue_wheel.py` e enviado ao bucket AUX
- Wheel compartilhado (`tmdb_shared`) com funções reutilizadas entre jobs (retry HTTP, triggers), gerado por `shared_src.tf` e referenciado via `--extra-py-files` junto ao wheel do job
- Argumentos padrão definidos no Terraform (buckets, nomes de tabelas, databases)
- Argumentos dinâmicos injetados no momento do `start_job_run` pela Lambda/job anterior

## Catálogo — Glue Catalog (`glue_catalog.tf`)

3 databases e 14 tabelas registradas via Terraform:

| Database | Tabelas |
|---|---|
| `db_tmdb_movie_{env}` | tb_tmdb_discover_movie_{env}, tb_tmdb_genre_movie_{env}, tb_tmdb_configuration_languages_{env}, tb_tmdb_details_movie_{env}, tb_tmdb_watch_providers_movie_{env}, tb_tmdb_watch_providers_ref_movie_{env}, tb_tmdb_now_playing_movie_{env} |
| `db_tmdb_tv_{env}` | tb_tmdb_discover_tv_{env}, tb_tmdb_genre_tv_{env}, tb_tmdb_configuration_countries_{env}, tb_tmdb_details_tv_{env}, tb_tmdb_watch_providers_tv_{env}, tb_tmdb_watch_providers_ref_tv_{env} |
| `db_tmdb_unified_{env}` | tb_tmdb_data_quality_{env} |

> Antes da introdução do prefixo `tmdb`, esses nomes de database/tabela não levavam sufixo de ambiente — uma inconsistência com a seção [Ambientes](overview.md#ambientes), já corrigida: agora `db_tmdb_movie_dev` e `db_tmdb_movie_prod` (por exemplo) são databases distintas.

> `tb_tmdb_discover_unified_{env}` (tabela SPEC) não é declarada via Terraform — é registrada dinamicamente pelo job Glue AGG em runtime.

> A tabela `now_playing` não possui partição de ano — é um snapshot completo sobrescrito diariamente (`mode=overwrite`), diferente das tabelas `discover` que são particionadas por ano. Inclui os campos `theater_start_date` e `theater_end_date` com a janela de exibição reportada pela API do TMDB.

## Servidor — Lightsail (`lightsail_ia.tf`)

- Instância `tmdb-filmbot-{env}` (`micro_3_0` — 2 vCPU, 1 GB RAM, $7/mês) para hospedar o app Streamlit
- **Caddy** como proxy reverso na porta 80
- Streamlit escuta apenas em `127.0.0.1:8501` (não acessível diretamente pela internet)
- Portas abertas: 22 (SSH — CIDR configurável via `lightsail_ssh_allowed_cidrs`), 80 (redirect HTTP→HTTPS + ACME challenge), 443 (HTTPS — proxy reverso para Streamlit)
- IP estático fixo (`tmdb-filmbot-static-ip-{env}`) para URL estável
- IAM user `tmdb-filmbot-agent-{env}` com acesso mínimo a Athena, S3 SPEC/TEMP e Glue Catalog
- Controlado pela variável `lightsail_enabled` (default `true`). Em `dev` está desabilitado (`false`) — a instância não é criada e o CI/CD ignora o deploy SSH. Para reativar: mudar para `true` em `infra/envs/dev/terraform.tfvars` e fazer push no `develop`.
- Quando habilitada, o workflow de deploy verifica o estado da instância via `aws lightsail get-instance` antes de tentar o SSH. Se a instância estiver parada (ex: fora do horário do scheduler), o deploy é **ignorado com warning** em vez de falhar por timeout.

**Agendamento de custo** (`lightsail_scheduler.tf`): Lambda + EventBridge com 3 regras de schedule. Desliga todos os dias às **00:00 BRT** (`cron(00 03 ? * * *)`); inicia às **18:00 BRT de seg–sex** (`cron(00 21 ? * MON-FRI *)`) e às **08:00 BRT aos sáb–dom** (`cron(00 11 ? * SAT-SUN *)`). Habilitado apenas quando `lightsail_enabled = true`.
