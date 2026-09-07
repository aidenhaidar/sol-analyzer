variable "name" {
  default = "sol-analyzer"
}
variable "region" {
  default = "us-east-1"
}
variable "availability_zone" {
  default = "us-east-1a"
}
variable "key_name" {
  description = "EC2 key pair for SSH"
  type        = string
}
variable "admin_cidrs" {
  description = "CIDRs allowed to SSH"
  type        = list(string)
}
variable "api_domain" {
  description = "DNS name that points at the API EIP; Caddy fetches a certificate for it"
  type        = string
}
variable "api_shared_secret" {
  description = "Must match the Worker's API_SHARED_SECRET"
  type        = string
  sensitive   = true
}
variable "api_image" {
  default = "ghcr.io/aidenhaidar/sol-analyzer-api:latest"
}
variable "api_instance_type" {
  default = "c7a.xlarge"
}
variable "solana_cluster" {
  description = "mainnet-beta or testnet"
  default     = "mainnet-beta"
}
# A mainnet RPC node needs ~512 GB RAM and fast NVMe. r7i.16xlarge (512 GB) is the
# realistic floor; i4i instances bring local NVMe but their storage does not survive stop.
variable "rpc_instance_type" {
  default = "r7i.16xlarge"
}
variable "ledger_volume_gb" {
  default = 2000
}
variable "accounts_volume_gb" {
  default = 1000
}
# https://www.cloudflare.com/ips-v4 (refresh periodically)
variable "cloudflare_ipv4_cidrs" {
  type = list(string)
  default = [
    "173.245.48.0/20", "103.21.244.0/22", "103.22.200.0/22", "103.31.4.0/22",
    "141.101.64.0/18", "108.162.192.0/18", "190.93.240.0/20", "188.114.96.0/20",
    "197.234.240.0/22", "198.41.128.0/17", "162.158.0.0/15", "104.16.0.0/13",
    "104.24.0.0/14", "172.64.0.0/13", "131.0.72.0/22",
  ]
}
