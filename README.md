# Pipeline de Dados de Filmes e Séries — AWS

Este projeto é um pipeline automatizado que coleta, processa e organiza informações sobre filmes e séries a partir da [API do TMDB](https://www.themoviedb.org/), e as disponibiliza para um aplicativo de recomendações com inteligência artificial.

---

## O que o sistema faz

Todos os dias, o sistema acorda sozinho, vai até uma fonte pública de dados de filmes e séries, coleta as informações mais recentes, as organiza em camadas de dados cada vez mais refinadas, valida a qualidade dos dados e, ao final, deixa tudo pronto para o aplicativo de recomendações consultar.

Além dos dados de descoberta de novos títulos, o sistema também coleta diariamente quais filmes estão atualmente em cartaz nos cinemas, enriquecendo o catálogo com as datas de janela teatral.

O usuário final interage apenas com o aplicativo: digita o que gosta ("filmes de terror dos anos 90", "séries de comédia na Netflix") e recebe recomendações personalizadas com pôster, sinopse, avaliação e onde assistir.

---

## Fluxo geral

```
Todos os dias, automaticamente:

  [Agendador] ──► [Coletor de dados] ──► [Transformador] ──► [Validador]
                                                    │
                                                    ▼
                                          [Enriquecedor]  ──► [Validador]
                                                    │
                                                    ▼
                                           [Unificador]  ──► [App de Recomendações]
```

---

## Camadas de dados (arquitetura medalhão)

Os dados passam por quatro camadas progressivas de refinamento, cada uma com um propósito diferente:

- **SOR (System of Record)** — dados brutos, exatamente como vieram da fonte (API TMDB). Formato JSON. Nenhuma transformação é feita aqui.
- **SOT (Source of Truth)** — dados convertidos para Parquet, estruturados e particionados. É a camada de análise intermediária, consultável via SQL com Athena.
- **SPEC (Specification / Gold)** — tabela final unificada, com filmes e séries juntos, já traduzidos e sem duplicatas. É a camada que o app de recomendações consulta.
- **DQ (Data Quality)** — resultados das validações de qualidade. Registra quais regras passaram ou falharam em cada execução do pipeline.

---

## Serviços do projeto

### Coletor de dados (Lambda API)
Responsável por buscar dados de filmes e séries diretamente na API do TMDB. Coleta informações como título, nota, gênero, idioma, plataformas de streaming disponíveis no Brasil e muito mais. Além dos dados de descoberta, coleta diariamente filmes em cartaz nos cinemas (endpoint `now_playing`), registrando as datas de início e fim da janela teatral de cada filme. Ao terminar, aciona o próximo passo automaticamente.

### Transformador (Glue ETL)
Recebe os dados brutos coletados e os organiza em um formato estruturado e eficiente para análise. É como passar de uma pilha de papéis avulsos para uma planilha bem organizada. Ao terminar, aciona os próximos passos.

### Validador de qualidade (Glue Data Quality)
Verifica se os dados estão corretos antes de avançar no pipeline. Checa se há registros duplicados, se os campos obrigatórios estão preenchidos, se as notas estão dentro do intervalo válido, entre outras regras. Se algo estiver errado, envia uma notificação por e-mail.

### Enriquecedor (Glue Details)
Busca informações complementares para cada filme e série: duração dos filmes, número de temporadas e episódios das séries, e as plataformas de streaming onde estão disponíveis no Brasil. Também traduz títulos e sinopses do inglês para o português. Ao terminar, aciona o unificador.

### Unificador (Glue AGG)
Junta tudo — filmes e séries, com todos os seus detalhes — em uma única tabela final. Enriquece cada filme com a informação de se está atualmente em cartaz nos cinemas (`in_theaters`) e, quando aplicável, as datas de início e fim da janela teatral. Essa tabela é a fonte de dados do aplicativo de recomendações.

### Aplicativo de recomendações (FilmBot — Lightsail)
Interface web onde o usuário digita o que quer assistir em linguagem natural. Um agente de IA interpreta o pedido, consulta a base de dados e retorna recomendações personalizadas com pôster, sinopse, avaliação, duração e onde assistir.

---

## Infraestrutura

O projeto roda inteiramente na AWS e é gerenciado como código — qualquer mudança na infraestrutura é feita por arquivos de configuração, não manualmente. Há dois ambientes isolados: **dev** (desenvolvimento) e **prod** (produção), cada um em uma conta AWS separada.

O pipeline é acionado automaticamente por um agendador (EventBridge) e cada etapa aciona a próxima ao terminar, sem intervenção humana.

---

## CI/CD

Qualquer alteração no código passa por um processo automatizado de validação antes de chegar à produção:

| Branch | O que acontece |
|---|---|
| `feature/*` | Testes (lint, cobertura ≥ 80%, type check, segurança) → PR automático para `develop` |
| `develop` | Terraform apply no ambiente `dev` → PR automático para `main` |
| `main` | Terraform apply no ambiente `prod` → deploy do FilmBot no Lightsail |

O pipeline é orquestrado por 5 workflows em `.github/workflows/`. Consulte [`.github/workflow.md`](.github/workflow.md) para a documentação completa.

---

## Tecnologias

| Camada | Tecnologia |
|---|---|
| Linguagem | Python 3 |
| Infraestrutura como código | Terraform `>= 1.5.0` |
| CI/CD | GitHub Actions |
| Processamento de dados | AWS Glue (PySpark), AWS Lambda |
| Armazenamento | AWS S3 (arquitetura medalhão — 4 camadas: SOR → SOT → SPEC → DQ), AWS Glue Catalog (catálogo de metadados), AWS Athena (consultas SQL sobre o S3) |
| Observabilidade | AWS CloudWatch, AWS SNS |
| Interface web | Streamlit (hospedado no AWS Lightsail) |
| Inteligência artificial | LLM via API compatível (recomendações e extração de filtros) |

---

## Estrutura do repositório

```
app/         → código de cada serviço do pipeline
infra/       → infraestrutura AWS (Terraform)
test/        → testes automatizados por serviço
.github/     → pipelines de CI/CD (GitHub Actions)
```

Para documentação técnica detalhada, consulte os arquivos `.md` dentro de cada pasta de serviço.
