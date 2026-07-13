#!/usr/bin/env bash
# Gera app/lightsail_ia/.env com as credenciais do ambiente dev lidas do Terraform.
# Uso: LLM_API_KEY=sk-... [TRANSCRIPTION_API_KEY=gsk_...] bash infra/config/export_env_local.sh
#
# Em dev local, LLM_API_KEY é usada diretamente (fallback quando FILMBOT_SECRET_ARN
# não está definida). Em produção, o app busca do Secrets Manager via FILMBOT_SECRET_ARN.
#
# TRANSCRIPTION_API_KEY é opcional: sem ela, a transcrição de áudio fica indisponível,
# mas o resto do app (campo de texto, recomendação) funciona normalmente.
set -euo pipefail

: "${LLM_API_KEY:?Defina LLM_API_KEY antes de rodar este script}"
: "${TRANSCRIPTION_API_KEY:=}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

ENV_FILE="$SCRIPT_DIR/../../app/lightsail_ia/.env"

echo "Lendo outputs do Terraform (dev)..."
ACCESS_KEY=$(terraform output -raw lightsail_agent_access_key_id)
SECRET_KEY=$(terraform output -raw lightsail_agent_secret_access_key)

cat > "$ENV_FILE" <<EOF
LLM_API_KEY=$LLM_API_KEY

AWS_REGION=sa-east-1
AWS_ACCESS_KEY_ID=$ACCESS_KEY
AWS_SECRET_ACCESS_KEY=$SECRET_KEY
ATHENA_S3_OUTPUT=s3://lsg-sa-east-1-bucket-temp-prod/tmdb/athena/lightsail_ia
GLUE_DATABASE=db_tmdb_unified_prod
SPEC_TABLE=tb_tmdb_discover_unified_prod

TRANSCRIPTION_MODEL=groq/whisper-large-v3-turbo
TRANSCRIPTION_API_KEY=$TRANSCRIPTION_API_KEY
EOF

echo ".env criado em $ENV_FILE"
if [ -z "$TRANSCRIPTION_API_KEY" ]; then
  echo "Aviso: TRANSCRIPTION_API_KEY não definida — transcrição de áudio ficará indisponível."
fi
echo "Para rodar: cd app/lightsail_ia && streamlit run app.py"
