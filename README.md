# Pipeline de Dados de Filmes e Séries — AWS

Este projeto é um pipeline automatizado que coleta, processa e organiza informações sobre filmes e séries a partir da [API do TMDB](https://www.themoviedb.org/), e as disponibiliza para um aplicativo de recomendações com inteligência artificial.

---

## O que o sistema faz

Todos os dias, o sistema acorda sozinho, vai até uma fonte pública de dados de filmes e séries, coleta as informações mais recentes, as organiza em camadas de dados cada vez mais refinadas, valida a qualidade dos dados e, ao final, deixa tudo pronto para o aplicativo de recomendações consultar.

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

## Serviços do projeto

### Coletor de dados (Lambda API)
Responsável por buscar dados de filmes e séries diretamente na API do TMDB. Coleta informações como título, nota, gênero, idioma, plataformas de streaming disponíveis no Brasil e muito mais. Ao terminar, aciona o próximo passo automaticamente.

### Transformador (Glue ETL)
Recebe os dados brutos coletados e os organiza em um formato estruturado e eficiente para análise. É como passar de uma pilha de papéis avulsos para uma planilha bem organizada. Ao terminar, aciona os próximos passos.

### Validador de qualidade (Glue Data Quality)
Verifica se os dados estão corretos antes de avançar no pipeline. Checa se há registros duplicados, se os campos obrigatórios estão preenchidos, se as notas estão dentro do intervalo válido, entre outras regras. Se algo estiver errado, envia uma notificação por e-mail.

### Enriquecedor (Glue Details)
Busca informações complementares para cada filme e série: duração dos filmes, número de temporadas e episódios das séries, e as plataformas de streaming onde estão disponíveis no Brasil. Ao terminar os filmes e séries, aciona o unificador.

### Unificador (Glue AGG)
Junta tudo — filmes e séries, com todos os seus detalhes — em uma única tabela final. Também traduz títulos e sinopses do inglês para o português. Essa tabela é a fonte de dados do aplicativo de recomendações.

### Aplicativo de recomendações (FilmBot — Lightsail)
Interface web onde o usuário digita o que quer assistir em linguagem natural. Um agente de IA interpreta o pedido, consulta a base de dados e retorna recomendações personalizadas com pôster, sinopse, avaliação, duração e onde assistir.

---

## Infraestrutura

O projeto roda inteiramente na AWS e é gerenciado como código — qualquer mudança na infraestrutura é feita por arquivos de configuração, não manualmente. Há dois ambientes isolados: **dev** (desenvolvimento) e **prod** (produção), cada um em uma conta AWS separada.

O pipeline é acionado automaticamente por um agendador (EventBridge) e cada etapa aciona a próxima ao terminar, sem intervenção humana.

---

## CI/CD

Qualquer alteração no código passa por um processo automatizado de validação antes de chegar à produção:

1. Os testes automatizados são executados
2. A infraestrutura é aplicada no ambiente de destino
3. Um Pull Request é criado automaticamente para revisão

---

## Tecnologias

| Camada | Tecnologia |
|---|---|
| Linguagem | Python 3 |
| Infraestrutura como código | Terraform `>= 1.5.0` |
| CI/CD | GitHub Actions |
| Processamento de dados | AWS Glue (PySpark), AWS Lambda |
| Armazenamento | AWS S3 (arquitetura medalhão), AWS Glue Catalog, AWS Athena |
| Observabilidade | AWS CloudWatch, AWS SNS |
| Interface web | Streamlit (hospedado no AWS Lightsail) |
| Inteligência artificial | OpenAI GPT-4o (recomendações e extração de filtros) |

---

## Estrutura do repositório

```
app/         → código de cada serviço do pipeline
infra/       → infraestrutura AWS (Terraform)
test/        → testes automatizados por serviço
.github/     → pipelines de CI/CD (GitHub Actions)
```

Para documentação técnica detalhada, consulte os arquivos `.md` dentro de cada pasta de serviço.
