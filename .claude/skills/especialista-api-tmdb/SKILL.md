---
name: especialista-api-tmdb
description: >-
  Especialista em consultar a documentação oficial da API do TMDB
  (https://developer.themoviedb.org/reference) antes de qualquer decisão de implementação que a envolva.
  TRIGGER — consultar a doc oficial via WebFetch ANTES de decidir, não depois de já ter escrito o código: sempre
  que for adicionar um endpoint novo, alterar parâmetros de uma chamada já existente (idioma, região,
  paginação, append_to_response, janela de datas do Changes API), mudar tratamento de rate limit/retry, ou
  implementar/revisar qualquer função que chame api.themoviedb.org (lambda_api, glue_details,
  shared_utils/api_client). Nunca decidir a partir de memória ou suposição sobre o comportamento da API — ela
  muda (endpoints descontinuados, parâmetros novos, limites de paginação/rate limit revisados) e os valores
  hardcoded no projeto podem estar desatualizados. SKIP quando a mudança não envolve nenhuma chamada HTTP nova
  ou alterada ao TMDB (ex.: transformação pura de dados já coletados, sem tocar parâmetros/endpoints da API).
---

# Especialista em API do TMDB

## Papel

Você garante que toda decisão sobre a API do TMDB — endpoint novo, parâmetro alterado, campo novo consumido,
mudança de paginação/rate limit/janela de datas — seja validada contra a **documentação oficial**
(https://developer.themoviedb.org/reference) antes de ser tomada, nunca a partir de memória ou suposição sobre
como a API "costuma" funcionar. A API do TMDB evolui (endpoints descontinuados, parâmetros novos, limites de
paginação/rate limit revisados), e todo comportamento hardcoded neste projeto reflete o que era verdade quando
foi escrito — não necessariamente o que é verdade hoje.

## Fontes de verdade (ler antes de agir)

Esta skill cobre o *gate* de consulta à API oficial; não repete o que já está documentado em outro lugar:

| O quê | Onde |
|---|---|
| Documentação oficial da API TMDB (fonte de verdade fora do repo — consulta primária antes de qualquer decisão) | https://developer.themoviedb.org/reference |
| Endpoints/parâmetros já em uso, modos de execução da Lambda | `app/lambda_api/lambda_api.md` |
| Enriquecimento de detalhes/watch providers, modo changes | `app/glue_details/glue_details.md` |
| Inventário de funções que chamam a API por módulo Lambda/Glue | `especialista-engenharia-dados-app` |
| Arquitetura funcional do pipeline, camadas S3, tabelas do Glue Catalog alimentadas pelos dados do TMDB | `projeto-filmes-aws` |
| Cliente HTTP compartilhado (retry/backoff, tratamento de rate limit) | `app/shared_src/shared_utils/api_client.py` |
| Onde a chave de API fica armazenada e como é lida (Secrets Manager) | `especialista-privilegio-minimo` |
| Checklist obrigatório pós-mudança (testes, docs, docstrings) | `revisao-testes-documentacao` |

## Práticas já aplicadas — preservar

- **Autenticação por `api_key` na query string** (não Bearer token), lida do Secrets Manager via
  `get_api_secret` uma única vez por execução — `app/lambda_api/src/utils.py` +
  `app/shared_src/shared_utils/api_client.py`.
- **`append_to_response` concatenando vários sub-recursos numa única chamada** por título
  (`credits,keywords,release_dates,videos,external_ids,recommendations,similar,alternative_titles,translations`,
  ou `content_ratings` no lugar de `release_dates` para tv) — `app/glue_details/src/utils.py:256`,
  `fetch_tmdb_details`.
- **Paginação com cap interno menor que o máximo real da API**: `MAX_PAGES = 100`
  (`app/lambda_api/src/utils.py:20`) — o TMDB permite até 500 páginas; o cap existe só para não estourar o
  timeout da Lambda, não porque 100 seja um limite da API.
- **Changes API com janela de 9 dias de lookback**, dentro do limite de 14 dias documentado pela própria API —
  `collect_changes_data` em `app/lambda_api/src/utils.py`.
- **Concorrência de `_TMDB_MAX_WORKERS = 20`** mantida abaixo do rate limit de ~40 req/s do TMDB —
  `app/glue_details/src/utils.py:285`.
- **Retry/backoff exponencial respeitando o header `Retry-After`** em 429, e tratando 500/502/503/504 como
  transitórios — `api_get` em `app/shared_src/shared_utils/api_client.py`.
- **`watch_region=BR` / `results.BR`** usados para escopar plataformas de streaming ao Brasil —
  `collect_watch_providers_ref` (`lambda_api`) e `fetch_tmdb_watch_providers`
  (`app/glue_details/src/utils.py:1076`).

## Lacunas encontradas — avaliar risco x esforço antes de agir

- **Nenhum dos limites hardcoded acima tem reconfirmação periódica contra a doc oficial.** `MAX_PAGES=100` (vs.
  500 real), a janela de 14 dias do Changes API, o rate limit de ~40 req/s e os campos aceitos por
  `append_to_response` foram fixados no momento em que o código foi escrito — se a API mudar qualquer um deles,
  nada no projeto sinaliza a divergência.
- **Endpoints não usados hoje** (ex. `/trending`, `/keywords/{id}` isolado, `/reviews`, `/account`) não têm
  comportamento validado neste projeto — antes de assumir que um endpoint fora desta lista não existe ou
  funciona de um jeito específico, confirmar na doc oficial em vez de generalizar a partir dos endpoints já
  conhecidos.

## Regras práticas ao escrever/revisar mudança nova

- **Antes de adicionar um endpoint novo, alterar parâmetros de uma chamada já existente, ou mudar tratamento de
  paginação/rate limit/janela de datas**: usar WebFetch para consultar
  `https://developer.themoviedb.org/reference/<endpoint>` e confirmar método HTTP, path exato, parâmetros
  obrigatórios/opcionais, formato de resposta e quaisquer limites documentados (paginação, rate limit, janela de
  datas) — nunca decidir a partir de memória sobre como a API "costuma" funcionar.
- **Ao tocar uma constante já hardcoded que reflete um limite do TMDB** (`MAX_PAGES`, janela do Changes API,
  `_TMDB_MAX_WORKERS`): reconfirmar o valor atual na doc oficial antes de mudar ou de assumir que o valor já
  documentado no projeto continua correto.
- **Todo endpoint/parâmetro novo adicionado precisa ser registrado** no `<modulo>.md` correspondente
  (`lambda_api.md`/`glue_details.md`) no mesmo PR — ver `especialista-documentacao`.
- **Se a doc oficial divergir do que está documentado no projeto** (`projeto-filmes-aws`,
  `especialista-engenharia-dados-app`), atualizar o `.md` do projeto no mesmo PR, não só o código.
