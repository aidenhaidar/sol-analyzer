output "api_public_ip" {
  value       = aws_eip.api.public_ip
  description = "Point api_domain's A record here, then set API_ORIGIN in web/wrangler.toml"
}
output "rpc_private_ip" {
  value = aws_instance.rpc.private_ip
}
output "rpc_public_ip" {
  value = aws_instance.rpc.public_ip
}
