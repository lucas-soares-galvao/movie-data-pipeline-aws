#!/usr/bin/env bash
# Gera app/lightsail_ia/.env com as credenciais e os nomes de recurso (Athena/Glue/
# Secrets Manager) lidos 100% dos outputs Terraform do workspace ativo — rode com o
# Terraform local inicializado (`terraform init -backend-config=...`) contra a conta
# dev ou prod. O IAM user do agente (aws_iam_access_key.lightsail_agent) existe nos
# dois ambientes — controlado por var.lightsail_agent_enabled (ver
# local.lightsail_agent_enabled em infra/locals.tf), independente da instância
# Lightsail em si (que só existe em prod). Rodar contra dev testa recommend()
# localmente com dados reais de dev, sem misturar credenciais com prod.
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
COGNITO_USER_POOL_ID=$(terraform output -raw lightsail_cognito_user_pool_id)
COGNITO_APP_CLIENT_ID=$(terraform output -raw lightsail_cognito_app_client_id)
SNS_NEW_SIGNUP_TOPIC_ARN=$(terraform output -raw lightsail_sns_new_signup_topic_arn)

# Fail-fast: sem isso, um FILMBOT_SECRET_ARN vazio (workspace errado, secret ainda
# não injetada) geraria um .env sem nenhuma chave, e o erro só apareceria depois,
# de forma confusa, quando o Streamlit tentasse chamar o LLM.
if [ -z "$FILMBOT_SECRET_ARN" ] && [ -z "$LLM_API_KEY" ]; then
  echo "❌ FILMBOT_SECRET_ARN veio vazia do Terraform e LLM_API_KEY não foi definida manualmente — defina uma das duas." >&2
  exit 1
fi

# Fail-fast: sem isso, o .env seria gerado com credenciais AWS vazias e o erro
# só apareceria depois, de forma confusa, ao chamar Athena/Glue/S3. Só acontece
# se var.lightsail_agent_enabled=false no workspace ativo (ver infra/locals.tf).
if [ -z "$ACCESS_KEY" ] || [ -z "$SECRET_KEY" ]; then
  echo "❌ AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY vieram vazios do Terraform — confirme que lightsail_agent_enabled=true no tfvars deste workspace." >&2
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
COGNITO_USER_POOL_ID=$COGNITO_USER_POOL_ID
COGNITO_APP_CLIENT_ID=$COGNITO_APP_CLIENT_ID
SNS_NEW_SIGNUP_TOPIC_ARN=$SNS_NEW_SIGNUP_TOPIC_ARN

TRANSCRIPTION_MODEL=groq/whisper-large-v3-turbo
TRANSCRIPTION_API_KEY=$TRANSCRIPTION_API_KEY
EOF
chmod 600 "$ENV_FILE"

echo ".env criado em $ENV_FILE"
if [ -z "$TRANSCRIPTION_API_KEY" ]; then
  echo "TRANSCRIPTION_API_KEY não foi passada na mão — o app vai buscar transcription_api_key do secret via FILMBOT_SECRET_ARN (indisponível só se o secret não tiver esse campo)."
fi
echo "Para rodar: cd app/lightsail_ia && streamlit run app.py"
