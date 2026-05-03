resource "aws_route53_zone" "main" {
  name = var.domain_name

  tags = {
    Name = var.domain_name
  }
}

resource "aws_route53_record" "wildcard_homelab" {
  zone_id = aws_route53_zone.main.zone_id
  name    = "*.homelab.${var.domain_name}"
  type    = "A"
  ttl     = 300
  records = [var.ingress_tunnel_eip]
}
