#!/usr/bin/env bash
# Gera app/lightsail_ia/.env com as credenciais do ambiente dev lidas do Terraform.
# Uso: LLM_API_KEY=sk-... bash infra/scripts/export_env_local.sh
set -euo pipefail

: "${LLM_API_KEY:?Defina LLM_API_KEY antes de rodar este script}"

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
EOF

echo ".env criado em $ENV_FILE"
echo "Para rodar: cd app/lightsail_ia && streamlit run app.py"
