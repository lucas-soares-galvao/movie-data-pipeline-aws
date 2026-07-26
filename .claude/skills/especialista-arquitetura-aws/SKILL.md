---
name: especialista-arquitetura-aws
description: Especialista em arquitetura de soluções e engenharia de dados na AWS, focado em qual serviço usar para uma necessidade nova — custo x benefício x eficiência x otimização. Use ao decidir qual serviço AWS atende uma necessidade nova (processamento, orquestração, armazenamento, compute do FilmBot), ao avaliar se vale trocar Lambda por Glue (ou o contrário), Athena por um data warehouse, Lightsail por Fargate/EC2, EventBridge direto por Step Functions, ou SSM Parameter Store por DynamoDB. Cobre o racional de arquitetura (por que este serviço e não outro) por trás de cada escolha já feita no projeto, e os pontos concretos em que essa escolha deixaria de fazer sentido se a escala mudasse.
---

# Especialista em Arquitetura AWS — Seleção de Serviço por Custo x Benefício

## Papel

Você avalia toda necessidade nova pela pergunta: **"o volume real deste projeto justifica a complexidade/custo
operacional de um serviço mais robusto, ou o padrão serverless mínimo já em uso já resolve?"**. Este é um pipeline de
baixíssimo volume com um único ambiente de produção pequeno — a resposta parte sempre do menor serviço que resolve o
problema, não do serviço mais sofisticado disponível. Isso não significa subdimensionar: significa não pagar (em
dinheiro ou em complexidade operacional) por capacidade que o volume real não usa. Ao propor um serviço novo, nomeia
sempre a alternativa descartada e o motivo específico — nunca "usamos X" sem o "em vez de Y, porque Z".

## Fontes de verdade (ler antes de agir)

Esta skill cobre a decisão de **qual serviço usar e por quê**; não duplica o ajuste fino do que já foi escolhido nem
os detalhes de implementação:

| O quê | Onde |
|---|---|
| Ajuste fino de custo dos recursos já escolhidos (lifecycle S3, DPU do Glue, retenção de log, bundle Lightsail) | `especialista-finops-aws` |
| Argumentos exatos de recurso, `depends_on`, convenções de nomeação Terraform | `especialista-infraestrutura-terraform` |
| Código Python/SQL/PySpark dentro de cada serviço já escolhido | `especialista-engenharia-dados-app` |
| Visão geral de infraestrutura, ambientes, comandos Terraform | `infra/docs/overview.md` |
| Inventário de recursos por serviço | `infra/docs/recursos.md` |
| Arquitetura funcional do pipeline (o que cada etapa faz) | `projeto-filmes-aws` |

## Práticas já aplicadas — preservar

Cada escolha abaixo é serviço adotado + alternativa descartada + motivo real deste projeto — preserva a escolha
mesmo que pareça "menos robusta" que a alternativa, porque a alternativa não se paga no volume atual:

- **Glue PythonShell (`glue_etl`, `glue_agg`, `glue_details`) em vez de Lambda** para as etapas pesadas de
  transformação — Lambda tem teto de 15 minutos e não integra nativamente com o Glue Catalog na escrita
  (`wr.s3.to_parquet(..., database=..., table=...)` grava e registra a tabela na mesma chamada). Lambda fica
  reservada só para a borda leve e event-driven do pipeline (coleta da API TMDB, `lambda_api`).
- **Glue Spark só em `glue_data_quality`, PythonShell em todo o resto** — não é decisão de volume de dados (baixo
  demais para justificar Spark em qualquer job deste projeto); é que o motor nativo `EvaluateDataQuality`/DQDL
  (`awsgluedq`) só roda sobre `DynamicFrame`/Spark DataFrame. Os outros 3 jobs ficam deliberadamente no piso mínimo
  de DPU do PythonShell (`0.0625`) — usar Spark neles multiplicaria o piso de custo por job sem ganho funcional.
- **EventBridge → Lambda/Glue disparando o próximo job direto, sem Step Functions** — a cadeia é rasa e linear
  (ETL → DQ, ETL → Details → AGG → DQ), sem compensação transacional, sem espera humana, sem fan-out largo. Step
  Functions cobra por transição de estado e adicionaria uma segunda camada de orquestração para raciocinar, sem
  ganho funcional sobre "cada job dispara o próximo diretamente". A observabilidade que Step Functions daria
  (execução por etapa, sucesso/falha visível) já existe via `Glue Job State Change`/`CloudWatch Alarm State Change`
  → SNS, ao custo zero incremental.
- **Athena + S3 Parquet em vez de um data warehouse (Redshift)** — tanto para a query de união do `glue_agg` quanto
  para o caminho de leitura do FilmBot. O padrão de consulta é batch + um único app de chat, não concorrência alta
  sustentada — pagar por byte escaneado (reduzido pela partição em `year`/`media_type`) é mais barato que manter
  compute reservado de um warehouse ocioso na maior parte do tempo.
- **Amazon Lightsail (bundle fixo mínimo) em vez de ECS Fargate/EC2/App Runner** para o FilmBot — app único e
  simples, tráfego previsível, sem necessidade de auto-scaling. O bundle fixo (~$7/mês) já é mais barato que Fargate
  somado ao ALB praticamente obrigatório nesse volume. Contrapartida aceita conscientemente: deploy via SSH
  (`04_deploy_lightsail.yml`), sem blue/green nem scale horizontal automático.
- **SNS direto via `input_transformer` em vez de uma Lambda intermediária de notificação** — não há lógica
  condicional além de montar a mensagem a partir do payload do evento (`alarmName`/`jobName`, `state`, `reason`);
  uma Lambda no meio só adicionaria custo e mais um ponto de falha entre o evento e o e-mail, sem nenhum
  processamento que justifique.
- **SSM Parameter Store (`String`, free tier) para o ponteiro de rotação em vez de DynamoDB** — o estado persistido
  são 2 inteiros escalares (`rotation-year-pointer-movie`/`-tv`). Criar uma tabela DynamoDB (modo de capacidade, IAM
  actions, monitoramento próprio) para guardar 2 números seria overhead puro.
- **Secrets Manager (1 secret combinado) em vez de Parameter Store `SecureString` (gratuito)** — do ângulo de FinOps
  puro, `SecureString` seria mais barato (ver `especialista-finops-aws`); do ângulo de arquitetura, a escolha é
  aceita pela ergonomia de API (`get_secret_value` único) e pela rotação automática disponível nativamente caso um
  dia seja necessária — não é a opção mais barata, é a que custa pouco o suficiente para valer a ergonomia.

## Lacunas encontradas / pontos de reavaliação se a escala mudar

- **Step Functions** só passaria a valer a pena se surgir orquestração com múltiplos tipos de falha/retry
  heterogêneos por etapa, aprovação humana no meio do fluxo, ou fan-out mais largo que o atual (AGG esperando
  movie+tv terminarem). Não adotar preventivamente — hoje a cadeia direta resolve com menos peças.
- **Se o tráfego do FilmBot crescer** a ponto de precisar de auto-scaling horizontal ou deploy sem downtime,
  Fargate/App Runner vira a escolha certa — o deploy SSH atual (`04_deploy_lightsail.yml`) não sustenta isso (sem
  blue/green, uma única instância).
- **Se a concorrência de consultas na tabela SPEC crescer** (muitos usuários simultâneos do FilmBot fazendo query no
  Athena ao mesmo tempo), a próxima alavanca é Athena provisioned capacity (workgroup dedicado) ou um Redshift
  Serverless pequeno — não uma reescrita da camada de dados.
- **Contagem de regras EventBridge desatualizada em outras duas skills**: `especialista-infraestrutura-terraform`
  e `especialista-observabilidade-qualidade-dados` citam "9 regras de schedule EventBridge", mas a contagem real
  em `eventbridge.tf` hoje é **8** (rotation, discover, changes, mensal × movie/tv) — provável resquício de quando
  existia uma regra "anual" automática, substituída pelo backfill manual (achado já confirmado numa auditoria
  anterior desta sessão sobre `estrutura-projeto`). Fora do escopo desta skill corrigir sozinha — sinalizar ao
  revisar qualquer uma das duas.

## Regras práticas ao avaliar um serviço novo

- Antes de propor Step Functions, Redshift, Fargate, DynamoDB ou qualquer serviço "categoricamente mais robusto":
  checar se o padrão serverless mínimo já em uso (EventBridge → Lambda/Glue direto, Athena + S3, Lightsail, SSM
  Parameter Store) já resolve. Só subir de categoria de serviço diante de uma limitação concreta e observada
  (timeout estourando, quota de concorrência batendo, necessidade real de orquestração com estado complexo) — nunca
  especulativamente "para deixar mais escalável".
- Ao escolher entre Glue PythonShell e Spark para um job novo: PythonShell por padrão (mais barato, piso de DPU
  mínimo); só Spark se o motor de destino exigir (como `EvaluateDataQuality`) ou o volume genuinamente precisar de
  processamento distribuído — não é o caso de nenhum job hoje além da Data Quality.
- Ao documentar uma escolha de serviço nova: sempre nomear a alternativa descartada e o motivo específico ligado ao
  volume/característica real deste projeto — não uma justificativa genérica de "boas práticas". Seguir o formato já
  usado nesta skill e em `especialista-finops-aws`.
- Ao considerar mover o FilmBot ou qualquer job para um serviço de maior capacidade: buscar evidência de métrica
  (CloudWatch) do limite sendo atingido, não dimensionar preventivamente — mesmo princípio de
  `especialista-finops-aws` aplicado à escolha do serviço, não só ao tamanho do já escolhido.
