#!/usr/bin/env bash
# Gera app/lightsail_ia/.env com as credenciais e os nomes de recurso (Athena/Glue/
# Secrets Manager) lidos 100% dos outputs Terraform do workspace ativo — rode com o
# Terraform local inicializado (`terraform init -backend-config=...`) contra a conta
# prod. FilmBot (Lightsail) não existe em dev — o IAM user do agente
# (aws_iam_access_key.lightsail_agent) só é criado em prod (ver
# local.lightsail_prod_enabled em infra/locals.tf), então rodar este script contra
# o state de dev geraria um .env com AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY vazios.
# Uso: bash infra/config/export_env_local.sh
#      [LLM_API_KEY=sk-...] [TRANSCRIPTION_API_KEY=gsk_...] bash infra/config/export_env_local.sh
#
# FILMBOT_SECRET_ARN vai no .env gerado, então o app busca llm_api_key/
# transcription_api_key/filmbot_password do Secrets Manager sozinho, igual já faz na
# instância Lightsail de prod (ver agent.py:_load_llm_api_key,
# infrastructure.py:load_filmbot_password) — não é preciso passar LLM_API_KEY/
# TRANSCRIPTION_API_KEY na mão. As env vars acima continuam aceitas só como override
# manual (ex.: testar uma chave/model diferente da que está no secret de dev).
set -euo pipefail

: "${LLM_API_KEY:=}"
: "${TRANSCRIPTION_API_KEY:=}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

ENV_FILE="$SCRIPT_DIR/../../app/lightsail_ia/.env"

echo "Lendo outputs do Terraform (workspace ativo)..."
ACCESS_KEY=$(terraform output -raw lightsail_agent_access_key_id)
SECRET_KEY=$(terraform output -raw lightsail_agent_secret_access_key)
ATHENA_S3_OUTPUT=$(terraform output -raw lightsail_athena_s3_output)
GLUE_DATABASE=$(terraform output -raw lightsail_glue_database)
SPEC_TABLE=$(terraform output -raw lightsail_spec_table)
FILMBOT_SECRET_ARN=$(terraform output -raw lightsail_filmbot_secret_arn)

# Fail-fast: sem isso, um FILMBOT_SECRET_ARN vazio (workspace errado, secret ainda
# não injetada) geraria um .env sem nenhuma chave, e o erro só apareceria depois,
# de forma confusa, quando o Streamlit tentasse chamar o LLM.
if [ -z "$FILMBOT_SECRET_ARN" ] && [ -z "$LLM_API_KEY" ]; then
  echo "❌ FILMBOT_SECRET_ARN veio vazia do Terraform e LLM_API_KEY não foi definida manualmente — defina uma das duas." >&2
  exit 1
fi

# Fail-fast: workspace de dev não tem mais o IAM user do agente (FilmBot só
# existe em prod) — sem isso, o .env seria gerado com credenciais AWS vazias
# e o erro só apareceria depois, de forma confusa, ao chamar Athena/Glue/S3.
if [ -z "$ACCESS_KEY" ] || [ -z "$SECRET_KEY" ]; then
  echo "❌ AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY vieram vazios do Terraform — rode este script contra o state de prod (FilmBot não existe em dev)." >&2
  exit 1
fi

cat > "$ENV_FILE" <<EOF
FILMBOT_SECRET_ARN=$FILMBOT_SECRET_ARN
LLM_API_KEY=$LLM_API_KEY

AWS_REGION=sa-east-1
AWS_ACCESS_KEY_ID=$ACCESS_KEY
AWS_SECRET_ACCESS_KEY=$SECRET_KEY
ATHENA_S3_OUTPUT=$ATHENA_S3_OUTPUT
GLUE_DATABASE=$GLUE_DATABASE
SPEC_TABLE=$SPEC_TABLE

TRANSCRIPTION_MODEL=groq/whisper-large-v3-turbo
TRANSCRIPTION_API_KEY=$TRANSCRIPTION_API_KEY
EOF
chmod 600 "$ENV_FILE"

echo ".env criado em $ENV_FILE"
if [ -z "$TRANSCRIPTION_API_KEY" ]; then
  echo "TRANSCRIPTION_API_KEY não foi passada na mão — o app vai buscar transcription_api_key do secret via FILMBOT_SECRET_ARN (indisponível só se o secret não tiver esse campo)."
fi
echo "Para rodar: cd app/lightsail_ia && streamlit run app.py"
