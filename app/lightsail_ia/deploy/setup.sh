#!/bin/bash
# Bootstrap da instância Lightsail para o FilmBot.
# Execute como root (ubuntu) logo após o primeiro SSH na instância.
#
# PRÉ-REQUISITO: antes de rodar este script, crie o arquivo .env em
#   /opt/filmbot/app/lightsail_ia/.env
# com as credenciais geradas pelo Terraform (terraform output).

set -e

REPO_URL="https://github.com/lucas-soares-galvao/proj-eng-dados-filmes-aws.git"
APP_DIR="/opt/filmbot"

apt-get update && apt-get install -y python3-pip python3-venv git

useradd -m filmbot || true  # ignora erro se o usuário já existir

git clone "$REPO_URL" "$APP_DIR"
chown -R filmbot:filmbot "$APP_DIR"

cd "$APP_DIR/app/lightsail_ia"
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

cp "$APP_DIR/app/lightsail_ia/deploy/filmbot.service" /etc/systemd/system/filmbot.service
systemctl daemon-reload
systemctl enable filmbot
systemctl start filmbot

echo "FilmBot iniciado. Acesse http://$(curl -s ifconfig.me):8501"
