output "zone_id" {
  description = "Route 53 hosted zone ID"
  value       = aws_route53_zone.main.zone_id
}

output "nameservers" {
  description = "Route 53 nameservers — update these at your domain registrar"
  value       = aws_route53_zone.main.name_servers
}
