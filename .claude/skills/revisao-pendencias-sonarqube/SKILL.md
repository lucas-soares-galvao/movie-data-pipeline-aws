---
name: revisao-pendencias-sonarqube
description: Consulta (somente leitura) as pendências do SonarQube Cloud deste repositório na aba Overall Code — Security, Reliability, Maintainability, Accepted Issues, Coverage, Duplications e Security Hotspots — via API pública do SonarCloud, e monta um relatório com o que está pendente por arquivo:linha, mais o status do Quality Gate. Use ao ser pedido "verifique/liste as pendências do Sonar", antes de começar a corrigir achados do Sonar, ou depois de um merge em main para confirmar que a análise zerou o que foi corrigido. Não corrige nem altera status de issue — a correção segue as skills de ponte da seção 5.
---

# Skill: Revisão das Pendências do SonarQube

Use esta skill para **descobrir o que está pendente** no SonarQube Cloud e apresentar o resultado. Ela só lê —
corrigir é um passo seguinte, guiado pelas skills de ponte (seção 5).

---

## 1. Escopo e ressalvas

- **Overall Code, branch `main`.** O relatório cobre o código inteiro, não só o "New Code" (o Quality Gate, ao
  contrário, é calculado em New Code — ver seção 4).
- **O Sonar só enxerga `main`.** `sonar.yml` roda apenas em `push:main` (plano Free só analisa a branch principal).
  Uma correção feita na branch de feature **só aparece depois do merge e de uma nova análise** — se o usuário acabou
  de corrigir algo localmente e o Sonar ainda mostra a pendência, isso não é falha da correção. Diga isso no
  relatório em vez de concluir que a correção não funcionou.
- **Informativo, não bloqueante.** O job não usa `sonar.qualitygate.wait=true`; o CI não falha por causa do Sonar.
- **Somente leitura.** Nunca marcar issue como `accepted`/`false positive` nem mudar status: isso exige token e a
  decisão de aceitar dívida é do usuário.

---

## 2. Fonte de dados

API pública do SonarCloud (o projeto é público — **não precisa de token**; validado com `curl` sem autenticação).

```bash
# Ler o valor real em sonar-project.properties (sonar.projectKey) antes de usar
P=lucas-soares-galvao_movie-data-pipeline-aws
B=https://sonarcloud.io/api
```

Se alguma chamada devolver `401`/`403`, o projeto deixou de ser público: pare e avise o usuário. Não peça nem cole
token na conversa ou em comando (ver `especialista-seguranca-segredos`).

| Dimensão (aba Overall Code) | Métricas (`measures/component`) | Detalhe por achado |
|---|---|---|
| **Security** | `software_quality_security_issues`, `security_rating` | `issues/search` (comando 2) — filtrar qualidade `SECURITY` |
| **Reliability** | `software_quality_reliability_issues`, `reliability_rating` | `issues/search` — qualidade `RELIABILITY` |
| **Maintainability** | `software_quality_maintainability_issues`, `sqale_rating` | `issues/search` — qualidade `MAINTAINABILITY` |
| **Accepted Issues** | `accepted_issues` | `issues/search?issueStatuses=ACCEPTED` (comando 3) |
| **Coverage** | `coverage` | `measures/component_tree` por arquivo (comando 5) |
| **Duplications** | `duplicated_lines_density` | `measures/component_tree` por arquivo (comando 5) |
| **Security Hotspots** | `security_hotspots`, `security_hotspots_reviewed` | `hotspots/search` (comando 4) |

Ratings vêm como número: `1.0`=A, `2.0`=B, `3.0`=C, `4.0`=D, `5.0`=E. Só `1.0` (A) é "sem pendência".

---

## 3. Comandos

Sem `jq` (não existe no Git Bash do ambiente): os one-liners usam `python -c`.

**1. Visão geral — as 7 dimensões numa chamada**

```bash
curl -s "$B/measures/component?component=$P&metricKeys=software_quality_security_issues,security_rating,software_quality_reliability_issues,reliability_rating,software_quality_maintainability_issues,sqale_rating,accepted_issues,coverage,duplicated_lines_density,security_hotspots,security_hotspots_reviewed" | python -c "import sys,json; [print(f\"{m['metric']:45} {m['value']}\") for m in sorted(json.load(sys.stdin)['component']['measures'], key=lambda m: m['metric'])]"
```

Métrica ausente na resposta = ainda sem valor (ex.: projeto sem análise); não assuma `0`.

**2. Issues abertas (Security + Reliability + Maintainability)**

```bash
curl -s "$B/issues/search?componentKeys=$P&issueStatuses=OPEN,CONFIRMED&ps=500" | python -c "import sys,json; d=json.load(sys.stdin); print('total', d['paging']['total']); [print(i['impacts'][0]['softwareQuality'], i['impacts'][0]['severity'], i['component'].split(':',1)[1]+':'+str(i.get('line','-')), i['rule'], i['message'], sep=' | ') for i in d['issues']]"
```

`ps=500` é o máximo por página; se `total` for maior, repetir com `&p=2`, `&p=3`… Qualidade e severidade vêm de
`impacts` (modelo de impacto atual do Sonar), não dos campos legados `type`/`severity`.

**3. Accepted Issues (com a justificativa registrada)**

```bash
curl -s "$B/issues/search?componentKeys=$P&issueStatuses=ACCEPTED&additionalFields=comments&ps=500" | python -c "import sys,json; d=json.load(sys.stdin); print('total', d['paging']['total']); [print(i['component'].split(':',1)[1]+':'+str(i.get('line','-')), i['rule'], [c.get('markdown') for c in i.get('comments',[])], sep=' | ') for i in d['issues']]"
```

Para cada uma, checar se a justificativa ainda vale — Accepted é dívida assumida, não resolvida.

**4. Security Hotspots a revisar**

```bash
curl -s "$B/hotspots/search?projectKey=$P&status=TO_REVIEW&ps=500" | python -c "import sys,json; d=json.load(sys.stdin); print('total', d['paging']['total']); [print(h['vulnerabilityProbability'], h['component'].split(':',1)[1]+':'+str(h.get('line','-')), h['ruleKey'], h['message'], sep=' | ') for h in d['hotspots']]"
```

**5. Piores arquivos de Coverage e de Duplications**

```bash
for M in uncovered_lines duplicated_lines; do echo "-- $M"; curl -s "$B/measures/component_tree?component=$P&metricKeys=coverage,uncovered_lines,duplicated_lines,duplicated_lines_density&qualifiers=FIL&s=metric&metricSort=$M&metricSortFilter=withMeasuresOnly&asc=false&ps=10" | python -c "import sys,json; [print(c['path'], {m['metric']: m['value'] for m in c['measures']}, sep=' | ') for c in json.load(sys.stdin)['components']]"; done
```

Se todo arquivo listado em `duplicated_lines` tem `0`, não há duplicação — a ordenação só devolve os "primeiros"
de qualquer forma.

**6. Quality Gate**

```bash
curl -s "$B/qualitygates/project_status?projectKey=$P" | python -c "import sys,json; s=json.load(sys.stdin)['projectStatus']; print(s['status']); [print(c['metricKey'], c['status'], c['actualValue'], sep=' | ') for c in s['conditions']]"
```

---

## 4. Particularidades deste repo (evitam diagnosticar "bug de config" que é intencional)

- **O Quality Gate é sobre New Code** (`new_*`, período `previous_version`), não sobre Overall Code. Ele pode estar
  `ERROR` por uma issue nova enquanto o Overall mostra números quase limpos — reporte os dois, sem confundi-los.
- **`sonar.python.version=3.9,3.12`**: jobs Glue PythonShell (`glue_etl`, `glue_details`) rodam em 3.9 e importam
  `shared_utils`; o resto roda em 3.12. Regras que sugerem sintaxe só de 3.12 (ex.: `python:S6796`, PEP 695) podem
  quebrar em 3.9 — antes de "corrigir", conferir em qual runtime o arquivo roda (`especialista-doc-oficial-codigo`).
- **`sonar.exclusions=app/lightsail_ia/design/**`**: mockups de design ficam fora da análise.
- **`sonar.coverage.exclusions=app/lightsail_ia/static/js/**`**: JS estático não conta no Coverage (só Python é
  medido), mas continua analisado para bugs/smells/duplicação.
- **Coverage do Sonar ≠ gate do pytest.** O gate de 95% do CI vem de `pytest --cov=app --cov=scripts`; o `coverage`
  do Sonar usa o mesmo `coverage.xml`, mas é reportado por arquivo. Um arquivo abaixo de 95% no Sonar não quebra o CI
  enquanto o total ficar >= 95%.

---

## 5. Ponte para a correção

Esta skill não corrige. Depois de listar, use a skill que guia cada tipo de achado:

| Achado | Skill de ponte |
|---|---|
| Security / Hotspot em Python do FilmBot (SQL injection, PRNG, input externo) | `especialista-seguranca-filmbot` |
| Security por segredo/credencial hardcoded | `especialista-seguranca-segredos` |
| Maintainability (complexidade, nomes, código morto, TypeVar) | `especialista-legibilidade-codigo` + `especialista-doc-oficial-codigo` (sintaxe válida na versão do runtime) |
| Reliability (bug real) | `especialista-engenharia-dados-app` + `especialista-testes-app` (teste que trava a regressão) |
| Coverage | `especialista-testes-app` |
| Duplications | `especialista-engenharia-dados-app` (reuso de `app/shared_src`) |
| Regra desconhecida | página da regra em `https://rules.sonarsource.com/python/RSPEC-<numero>` (para `python:S2245`, número `2245`) |

Depois de corrigir, rodar `revisao-pos-mudanca-codigo`. Ao final, lembrar que o Sonar só reflete a correção depois do
merge em `main` (seção 1).

---

## 6. Formato do relatório

1. **Tabela das 7 dimensões**: `Dimensão | Valor | Rating | Status` (`ok` se rating A / contagem 0 / coverage e
   duplicação dentro do esperado; `pendente` caso contrário).
2. **Quality Gate (New Code)**: status e as condições em `ERROR`.
3. **Achados**, mais grave primeiro (severidade `BLOCKER` > `HIGH` > `MEDIUM` > `LOW` > `INFO`), agrupados por
   dimensão, cada um como link clicável `[arquivo:linha](caminho#Llinha)` + regra + mensagem.
4. **Accepted Issues** listadas com justificativa, e Coverage/Duplications com os arquivos mais afetados.
5. Link da UI para o usuário conferir:
   `https://sonarcloud.io/project/issues?id=<projectKey>&issueStatuses=OPEN%2CCONFIRMED`.
6. Se o usuário acabou de corrigir algo e o achado persiste, indicar a ressalva da seção 1.

---

## Como Aplicar

1. Ler `sonar.projectKey` em `sonar-project.properties` e definir `P`/`B` (seção 2).
2. Rodar o comando 1 (visão geral) e, para cada dimensão com pendência, o comando de detalhe correspondente
   (2 a 5); rodar o 6 para o Quality Gate.
3. Consultar a seção 4 antes de tratar como problema algo que é configuração intencional do repo.
4. Montar o relatório no formato da seção 6 e, se o usuário pedir para corrigir, seguir a seção 5.
