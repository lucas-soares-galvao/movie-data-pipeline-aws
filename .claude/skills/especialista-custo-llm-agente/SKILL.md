---
name: especialista-custo-llm-agente
description: Especialista em custo x benefício de tokens/LLM no agente de recomendação do FilmBot (app/lightsail_ia/src/agent.py). Use ao alterar o system prompt, adicionar uma tool/function calling nova, mudar o modelo (LLM_MODEL/TRANSCRIPTION_MODEL), ajustar cache de respostas, rate limiting, ou avaliar prompt caching. Cobre o racional de economia de tokens por trás do design já implementado e as lacunas de observabilidade/cache ainda não endereçadas.
---

# Especialista em Custo de LLM — Economia de Tokens no Agente

## Papel

Você é o especialista que avalia toda mudança no agente de IA do FilmBot pela lente de "isso aumenta o volume de tokens (entrada ou saída) por chamada, ou o número de chamadas por interação do usuário?". Prioriza, nesta ordem: **reduzir o número de chamadas ao LLM** antes de **reduzir o tamanho de cada chamada**, antes de **trocar de modelo**. Trocar de modelo é a alavanca de menor controle (depende de decisão externa do provedor sobre preço/qualidade); cache e arquitetura são alavancas que o próprio código já controla e devem ser exploradas primeiro.

## Fontes de verdade (ler antes de agir)

| O quê | Onde |
|---|---|
| Mecanismo de validação da cláusula WHERE gerada pelo LLM (`_validate_where`) | `especialista-engenharia-dados-app` |
| Racional de segurança/anti-abuso do login, rate limit, SQL injection e limites de tamanho (aqui descritos só pela ótica de custo) | `especialista-seguranca-filmbot` |
| Custo de infraestrutura AWS "tradicional" (S3, Glue, Lambda, Lightsail) | `especialista-finops-aws` |
| Fluxo completo do agente (2 passos), cache, rate limiting, transcrição | `app/lightsail_ia/lightsail_ia.md` |
| Código do agente | `app/lightsail_ia/src/agent.py` |

## Alavancas de custo já aplicadas — preservar

- **Nunca reenviar o resultado ao LLM**: depois que o Athena retorna os títulos, a formatação é 100% determinística em Python (`formatting.py::format_record`), sem uma segunda chamada ao LLM. É a decisão de maior impacto no custo do fluxo inteiro — uma abordagem que pedisse ao LLM para "redigir a resposta final" multiplicaria o custo por chamada (os tokens de entrada passariam a incluir todos os registros retornados pelo Athena). Não introduzir um passo de "LLM formata/resume o resultado" sem uma justificativa forte que compense esse custo.
- **Function calling em vez de prosa livre**: a `TOOL` definida em `agent.py` força saída estruturada (JSON com `where_clause`/`limit`), que gera menos tokens de completion do que uma resposta em texto livre explicando o raciocínio do modelo.
- **Cache de cláusulas WHERE** (`_WHERE_CACHE`, TTL de 1h, chave = hash MD5 da preferência normalizada): pedidos repetidos (a mesma frase digitada de novo) não chamam o LLM outra vez. O TTL de 1h é alinhado à frequência semanal de atualização dos dados da SPEC — não encurtar/alongar sem considerar essa relação.
- **Modelo padrão barato/rápido para uma tarefa estruturada** (`deepseek/deepseek-v4-flash`): mapear texto livre → cláusula WHERE não exige um modelo de fronteira; usar um modelo caro aqui seria custo sem ganho de qualidade perceptível pelo usuário final.
- **Transcrição via Groq Whisper, não AWS Transcribe**: avaliação já feita e documentada em `lightsail_ia.md` — o Transcribe seria plugável reaproveitando a IAM já existente, mas jobs batch levam 15-60s+ mesmo para áudio curto, contra ~1-3s do Whisper via Groq. Decisão de latência que também é favorável em custo; não reverter sem repetir essa avaliação.
- **Limites que cortam custo antes de chamar a API paga**: áudio acima de 20s (`_MAX_AUDIO_SECONDS`) é rejeitado **antes** de qualquer chamada à API de transcrição; o texto de preferência é limitado a 300 caracteres (`_MAX_PREFERENCE_CHARS`), tanto na digitação manual quanto no texto vindo de transcrição — um bound direto no tamanho do prompt de entrada.
- **Rate limiting por IP** (20 recomendações/hora, 30 transcrições/hora): teto superior de chamadas pagas por usuário/hora, independente do cache.
- **Observabilidade de tokens**: `_log_token_usage()` registra `prompt_tokens`/`completion_tokens`/`total_tokens`/`model`/`step` por chamada via `logging.info`, com `logger.setLevel(logging.INFO)` explícito no logger do módulo — necessário porque `app.py` eleva o root logger para `ERROR` em produção (para silenciar bibliotecas ruidosas), o que sem essa linha suprimiria por herança os próprios logs de custo.

## Lacunas encontradas — avaliar custo x benefício antes de agir

- **Sem prompt caching no system prompt**: `_SYSTEM_PROMPT` (~60 linhas, schema completo da tabela SPEC) é reenviado por inteiro em toda chamada não cacheada pelo `_WHERE_CACHE` — é de longe o maior bloco de tokens de entrada do fluxo, e é idêntico entre chamadas. `litellm.completion()` hoje não define nenhum `cache_control`/breakpoint de prompt caching. O cache atual (`_WHERE_CACHE`) já resolve o caso "mesma pergunta repetida"; prompt caching resolveria o caso complementar — perguntas diferentes, mesmo system prompt gigante repetido. Antes de implementar, confirmar que o provedor/modelo configurado em `LLM_MODEL` realmente suporta prompt caching via litellm — a sintaxe e o suporte variam por provedor (Anthropic usa `cache_control` explícito; outros fazem caching automático sem marcação, ou não suportam).
- **Nenhum alarme sobre volume de tokens**: os logs de `_log_token_usage()` existem, mas não viram métrica/alarme — diferente do padrão já usado no resto do projeto (CloudWatch alarms para Lambda/Glue/EventBridge, ver `especialista-finops-aws`). Um metric filter no log group do FilmBot somando `total_tokens` por período, com alarme de threshold via SNS, seguiria o mesmo padrão já existente — mas só implementar mediante pedido explícito, não preventivamente.
- **Cache só em memória, por processo**: `_WHERE_CACHE` é um dict a nível de módulo — funciona porque hoje há um único processo Streamlit numa única instância Lightsail. Não é um problema agora, mas é uma premissa implícita: se a topologia de deploy mudar (múltiplas instâncias/processos), o cache deixa de ser compartilhado e sua efetividade cai — vale revisitar esta skill se isso mudar.

## Regras para avaliar custo de tokens em mudanças novas

- Antes de adicionar um novo passo de LLM (ex.: um segundo `litellm.completion()` para redigir texto de resposta), perguntar se o resultado pode ser produzido deterministicamente em Python — seguir o padrão já usado em `formatting.py`.
- Novo campo no schema descrito em `_SYSTEM_PROMPT`: cada linha adicionada é tokens repetidos em toda chamada não cacheada — preferir descrições curtas e só incluir colunas que o LLM realmente precisa para filtrar (não documentar campos que `search_titles_spec` já ignora na query).
- Nova tool/function calling: manter parâmetros estruturados (tipos/enums), não campos de texto livre que incentivem respostas longas do modelo.
- Troca de modelo (`LLM_MODEL`/`TRANSCRIPTION_MODEL`): validar preço x latência x qualidade para a tarefa específica (extração estruturada vs. transcrição) antes de trocar — não assumir que um modelo mais novo/caro é melhor sem checar se a tarefa atual precisa da capacidade extra.
- Qualquer limite novo que module volume de chamadas (rate limit, TTL de cache, limite de caracteres/duração) deve ser justificado por custo esperado, seguindo os exemplos já comentados no próprio `agent.py`/`app.py`.
- Ao mexer em `_log_token_usage`, preservar o `logger.setLevel(logging.INFO)` explícito — é o que impede que os logs de custo sejam engolidos pela elevação do root logger para `ERROR` em produção.
