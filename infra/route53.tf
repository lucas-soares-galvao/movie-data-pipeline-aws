# Raciocinio: dev não tem static IP (ver local.lightsail_static_ip_enabled em
# infra/locals.tf) — o IP público muda a cada start da instância. Para manter
# o domínio filmbot-dev.lsgalvao.com.br funcionando, delegamos só esse
# subdomínio (via registro NS cadastrado manualmente uma única vez no
# registro.br) para uma hosted zone do Route 53, e o Terraform mantém o
# registro A atualizado a cada apply. O domínio raiz lsgalvao.com.br e o
# ambiente prod não são afetados — prod continua com static IP e DNS manual.

resource "aws_route53_zone" "filmbot_dev" {
  count = lower(var.env) == "dev" ? 1 : 0
  name  = "filmbot-dev.lsgalvao.com.br"
  tags  = merge(local.default_resource_tags, { Component = "lightsail_ia" })
}

# Criada uma única vez pelo apply completo do pipeline normal e nunca destruída
# (nem pelo scheduler, nem por um destroy/apply -target) — os name servers de
# uma hosted zone são estáveis pela vida do recurso; recriá-la invalidaria a
# delegação manual feita no registro.br.
output "route53_dev_name_servers" {
  description = "NS a cadastrar manualmente no painel do registro.br (uma única vez, delegação de subdomínio filmbot-dev.lsgalvao.com.br)"
  value       = lower(var.env) == "dev" ? try(aws_route53_zone.filmbot_dev[0].name_servers, []) : []
}

# Único recurso que o scheduler recria a cada start (05_lightsail_scheduler.yml)
# — reflete o IP dinâmico novo da instância a cada ciclo liga/desliga.
resource "aws_route53_record" "filmbot_dev" {
  count   = var.lightsail_enabled && lower(var.env) == "dev" ? 1 : 0
  zone_id = aws_route53_zone.filmbot_dev[0].zone_id
  name    = "filmbot-dev.lsgalvao.com.br"
  type    = "A"
  ttl     = 60
  records = [aws_lightsail_instance.filmbot[0].public_ip_address]
}
