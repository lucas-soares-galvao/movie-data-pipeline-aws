---
name: especialista-documentacao
description: Especialista em documentação do projeto — docs por módulo (`app/<modulo>/<modulo>.md`, `test/<modulo>/<modulo>_tests.md`), skills agregadoras (`estrutura-projeto.md`, `projeto-filmes-aws.md`) e skills de domínio (`especialista-*.md`). Use ao criar um módulo novo (app/ ou scripts/), ao adicionar/remover uma tabela, script, variável de ambiente, regra EventBridge ou modo de execução, ao escrever um `.md` novo em qualquer camada, ao avaliar se uma skill/doc existente ainda bate com o código atual, ou ao decidir se uma necessidade nova justifica criar uma skill, atualizar uma existente, ou mantê-la combinada com outra. Cobre os templates já em uso, o padrão de gap encontrado entre docs agregadoras e docs por módulo, o framework de decisão sobre o ciclo de vida das skills, e as lacunas de verificação automática ainda não endereçadas.
---

# Especialista em Documentação

## Papel

Você avalia toda mudança de código pela pergunta: **"existe um lugar que descreve isso, e ele ainda vai estar certo
depois desta mudança?"**. Documentação desatualizada tem o mesmo custo de um bug silencioso — só aparece quando
alguém confia nela para tomar uma decisão (um agente, um novo colaborador, você mesmo daqui a 6 meses). Não trata
documentação como tarefa separada de "escrever código": trata como parte da mesma mudança.

## Fontes de verdade (ler antes de agir)

Esta skill cobre convenções e racional de documentação; não duplica o conteúdo de cada doc:

| O quê | Onde |
|---|---|
| Convenção de idioma (prosa PT, identificadores EN), local de cada tipo de teste, quality gate, e o **índice completo de todas as skills existentes** | `CLAUDE.md` (raiz) |
| Checklist mecânico de "o que verificar" após qualquer mudança de código (testes, docs, docstrings, type hints) | `.claude/skills/revisao-testes-documentacao.md` |
| Árvore de diretórios, workflows CI/CD, estrutura Terraform, organização de testes | `.claude/skills/estrutura-projeto.md` |
| Arquitetura funcional do pipeline, tabelas, variáveis de ambiente, fluxo de eventos | `.claude/skills/projeto-filmes-aws.md` |
| Racional de domínio específico (IAM, Terraform, testes, segurança, FinOps, observabilidade/DQ, legibilidade, custo LLM, workflows GitHub) | os demais `.claude/skills/especialista-*.md` |

## Práticas já aplicadas — preservar

- **Doc por módulo de app (`app/<modulo>/<modulo>.md`)** segue um template fixo de 6 seções: `O que é` / `Por que
  existe` / `Como funciona` (passo a passo numerado) / `Entradas e saídas` (tabela) / `Funções principais` (tabela
  função → responsabilidade) / `Tecnologias`. Ver `app/glue_data_quality/glue_data_quality.md` como referência
  completa — inclui até uma explicação inline de DQDL para quem não conhece o Glue Data Quality, não assume
  conhecimento prévio do leitor.
- **Doc por módulo de teste (`test/<modulo>/<modulo>_tests.md`)** segue: `O que é testado` / `Estrutura` (árvore de
  arquivos) / `Casos de teste — <arquivo>` (uma tabela `Teste | O que verifica` por classe de teste) / `Como
  executar` / `Cobertura`. Ver `test/scripts/scripts_tests.md` como referência — o padrão mais maduro do projeto.
- **Bug real → parágrafo narrativo no `*_tests.md`, não só a tabela de casos.** Quando um teste existe para travar uma
  regressão específica, o doc conta a história (o que quebrou, por que passou despercebido, qual teste trava agora) —
  ver os 4 bugs narrados em `test/scripts/scripts_tests.md` (linhas 9-13): dois bugs de payload (`only_discover`/
  `skip_discover` — chaves que o Lambda handler nunca leu), um bug de wrapper de retry ausente, e um bug de
  reconhecimento incompleto de código de erro (`ExpiredToken` do S3 vs. `ExpiredTokenException` do STS). Isso é o
  que torna um teste compreensível sem precisar arqueologia de git blame.
- **Skill de domínio (`especialista-*.md`)** segue: `Papel` (a pergunta-guia do especialista) / `Fontes de verdade`
  (tabela — sempre a primeira seção depois do Papel) / `Práticas já aplicadas — preservar` / `Lacunas encontradas —
  avaliar risco x esforço antes de agir` / `Regras práticas ao escrever/revisar mudança nova`. A tabela de Fontes de
  verdade existe para impedir que a mesma explicação seja escrita duas vezes em skills diferentes — ver
  `.claude/skills/especialista-privilegio-minimo.md` como o exemplo mais completo do padrão.
- **CLAUDE.md raiz fica enxuto de propósito**: aponta para as skills em vez de descrever arquitetura — só repete o
  essencial (idioma, convenções de teste, comandos úteis) que qualquer sessão precisa mesmo sem carregar uma skill.

## Lacunas encontradas — avaliar risco x esforço antes de agir

- **Nada no CI verifica se um `.md` ainda bate com o código.** A suíte de testes (`pytest --cov=app`) cobre `app/`;
  não existe um lint ou teste que confira se um número, nome de variável ou fluxo citado numa skill/doc ainda existe
  no código. Confirmado nesta mesma sessão: `projeto-filmes-aws.md` e `estrutura-projeto.md` (as duas skills
  "agregadoras" listadas em `CLAUDE.md`) acumularam divergências reais — contagem de policies do CI/CD desatualizada,
  ranges DQDL citando colunas (`budget`, `revenue`) que não existem em `rulesets_dq.py`, tabela de variáveis de
  ambiente da Lambda incompleta, um modo inteiro da Lambda (`only_rotation_refresh`) e um `table_group` inteiro do
  backfill manual (`rename_colunas`) não documentados em lugar nenhum — sem que nada sinalizasse o gap até uma
  auditoria manual linha a linha contra `infra/*.tf`, `app/lambda_api/main.py` e `.github/workflows/05_backfill.yml`.
- **Padrão do gap: docs agregadores driftam, docs por módulo não.** `scripts/scripts.md` e `test/scripts/
  scripts_tests.md` (que descrevem só os 7 scripts de `scripts/`) estavam corretos e completos; `estrutura-projeto.md`
  (que resume a mesma lista de scripts numa árvore de diretório) estava desatualizado. Hipótese: quem edita um módulo
  tem o reflexo de atualizar o doc ao lado, mas não o de voltar aos agregadores que citam o mesmo fato em forma
  resumida. Ao revisar uma skill agregadora, tratar cada número/lista como suspeito até confirmar contra o código —
  não confiar em busca textual por palavra-chave, que não pega omissão (um item que deveria estar na lista e não
  está não aparece em nenhum grep).
- **`.github/workflow.md` tem a mesma contagem desatualizada de "6 policies"** que foi corrigida em
  `projeto-filmes-aws.md` nesta sessão — fora do escopo das 3 skills já auditadas, mas no mesmo raio de risco
  (qualquer doc que cite uma contagem específica do `iam_cicd.tf` tende a ficar velho quando a 7ª policy, `cicd_ssm`,
  ou uma futura 8ª, for adicionada). Vale revisar na próxima auditoria de documentação, não apenas as skills.
- **As skills em `.claude/skills/` são arquivos `.md` soltos, não `.claude/skills/<nome>/SKILL.md`** — por isso
  nenhuma delas aparece na listagem de skills disponíveis que o Skill tool injeta automaticamente na conversa (só
  skills globais, ex. `aws-serverless`, `dataviz`, aparecem lá). Carregar uma especialista-*.md deste projeto é
  sempre decisão manual (`Read` explícito) de quem está trabalhando na tarefa — o índice em `CLAUDE.md` ("Skills
  para Contexto Detalhado") é hoje o único mecanismo de roteamento; ao criar, remover ou renomear uma skill,
  atualizar esse índice no mesmo PR, ou a skill "existe mas ninguém a encontra". Migrar para a estrutura
  `SKILL.md` ativaria auto-discovery nativo, mas exigiria mover os 16 arquivos e reescrever toda referência cruzada
  por caminho nas tabelas de Fontes de verdade — mudança grande demais para fazer sem pedido explícito.

## Decisão: criar skill nova, atualizar existente, ou manter combinada

Framework usado para decidir o ciclo de vida de uma skill, extraído de 3 decisões reais já tomadas no projeto:

1. **A pergunta já é respondida (mesmo que parcialmente) por uma skill existente?** Atualizar essa skill — nunca
   criar uma nova que duplique. Ex.: os gaps de contagem/lista corrigidos em `estrutura-projeto.md` e
   `projeto-filmes-aws.md` (ver "Lacunas encontradas" acima) foram correções nos arquivos existentes, não skills novas.
2. **É uma pergunta nova, mas tecnicamente acoplada a uma skill existente** (compartilha o mesmo mecanismo/recurso;
   explicar uma sem a outra duplicaria contexto)? Manter combinado / expandir a existente, não separar. Ex.:
   avaliação de separar `especialista-observabilidade-qualidade-dados.md` em observabilidade + qualidade de dados —
   decisão de **não** separar, porque falha de job e falha de regra DQ passam pelo mesmo padrão
   `EventBridge → SNS` e a skill precisa explicar os dois tópicos juntos para não confundi-los.
3. **É uma pergunta genuinamente nova, sem acoplamento técnico forte com nenhuma skill existente?** Criar skill
   nova, seguindo o template padrão. Ex.: `especialista-documentacao.md` (nenhuma skill cobria templates/drift de
   docs) e `especialista-arquitetura-aws.md` (nenhuma skill cobria "por que este serviço AWS e não outro" — as
   skills adjacentes de FinOps/Terraform/engenharia de dados cobrem custo do já escolhido, implementação e código,
   não a escolha em si).
4. **Antes de criar, checar o tamanho/substância esperado**: um `especialista-*.md` novo deve sustentar a faixa de
   ~44-140 linhas já observada no projeto, com pelo menos 3-5 "práticas já aplicadas" citando arquivo/linha real —
   se o conteúdo não sustenta isso, provavelmente cabe como seção dentro de uma skill existente, não como arquivo
   novo (foi assim que o framework desta seção acabou aqui, em vez de virar uma 4ª skill nova).

Ao terminar de criar, atualizar ou remover uma skill: atualizar o índice em `CLAUDE.md` no mesmo PR (ver bullet
acima em "Lacunas encontradas").

## Regras práticas ao escrever/revisar mudança nova

- **Tabela nova, script novo, variável de ambiente nova, regra EventBridge nova, ou modo de execução novo**:
  atualizar o `<modulo>.md` (ou `<modulo>_tests.md`) no mesmo PR — e perguntar explicitamente se
  `estrutura-projeto.md` e/ou `projeto-filmes-aws.md` também citam esse mesmo fato em forma resumida (árvore de
  diretório, tabela de variáveis, lista de regras). Se citam, atualizar os dois no mesmo PR — não depender de uma
  auditoria futura para pegar o gap.
- **Skill de domínio nova (`especialista-*.md`)**: seguir o template de 5 seções (Papel / Fontes de verdade /
  Práticas já aplicadas / Lacunas encontradas / Regras práticas), começando pela tabela de Fontes de verdade para não
  duplicar o que já vive em outra skill.
- **Doc de módulo novo (`app/<modulo>/<modulo>.md` ou `test/<modulo>/<modulo>_tests.md`)**: seguir o template já
  padronizado (seções acima), incluindo o parágrafo de "bug real" no `*_tests.md` quando um teste existir para travar
  uma regressão específica — não só listar o teste na tabela.
- **Ao auditar se uma skill/doc precisa de atualização**: confirmar cada número e nome citado por leitura direta do
  código-fonte relevante (`.tf`, `main.py`/`utils.py`, `rulesets_dq.py`, workflows `.yml`) — grep de palavra-chave não
  pega itens ausentes (uma tabela, flag ou script que deveria estar listado e não está não aparece em nenhuma busca
  textual).
