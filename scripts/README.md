# Scripts utilitários

Scripts de uso pontual para operações manuais no pipeline. Não fazem parte do fluxo automatizado (CI/CD).

## Pré-requisitos

- Python 3.12+ com as dependências do projeto instaladas
- Credenciais AWS configuradas (`aws configure` ou variáveis de ambiente)
- Variáveis de ambiente específicas de cada script (documentadas no cabeçalho de cada arquivo)

## Scripts disponíveis

| Script | O que faz | Quando usar |
|---|---|---|
| `backfill_historico.py` | Popula as tabelas discover de 2000 até o ano atual, invocando a Lambda ano a ano | Primeira carga do pipeline ou para reprocessar dados históricos |
| `backfill_traducao.py` | Adiciona traduções PT-BR (title_pt, overview_pt) aos detalhes históricos já existentes | Após o backfill histórico, para traduzir títulos e sinopses que ficaram sem tradução |
| `backfill_data_quality.py` | Aciona o job Glue Data Quality para todas as tabelas e anos (2000–atual) em lotes assíncronos | Após backfill histórico, para validar a qualidade dos dados retroativamente |

## Como executar

```bash
# Configure as variáveis de ambiente (veja o cabeçalho de cada script)
export AWS_REGION=sa-east-1
export S3_BUCKET_SOT=lsg-sa-east-1-bucket-sot-prod
# ... (demais variáveis)

# Execute o script desejado
python scripts/backfill_historico.py
```
