# All inputs. Values with a default can be overridden in terraform.tfvars;
# the ones without a default (do_token, my_ip, registry_name) you must supply.

variable "do_token" {
  description = "DigitalOcean API token (write access). Supply via terraform.tfvars or TF_VAR_do_token."
  type        = string
  sensitive   = true # Terraform will mask it in output/logs
}

variable "region" {
  description = "DO region. sgp1 = Singapore (closest to you)."
  type        = string
  default     = "sgp1"
}

variable "name" {
  description = "Base name for all resources."
  type        = string
  default     = "macro-rag"
}

# ── Kubernetes cluster ─────────────────────────────────────────────
variable "node_size" {
  description = "Worker node size. s-2vcpu-4gb ≈ $28/mo each."
  type        = string
  default     = "s-2vcpu-4gb"
}

variable "node_count" {
  description = "Number of worker nodes. 2 gives headroom + teaches multi-node; lower to 1 to save."
  type        = number
  default     = 2
}

# ── Managed Postgres ───────────────────────────────────────────────
variable "pg_version" {
  description = "Postgres major version. 16 supports pgvector."
  type        = string
  default     = "16"
}

variable "db_size" {
  description = "Managed DB node size. db-s-1vcpu-2gb ≈ $30/mo."
  type        = string
  default     = "db-s-1vcpu-2gb"
}

# ── Container registry ─────────────────────────────────────────────
variable "registry_name" {
  description = "Globally-unique registry name (across ALL of DigitalOcean). Pick something like macro-rag-<yourname>."
  type        = string
}

# ── One-time data load access ──────────────────────────────────────
variable "my_ip" {
  description = "Your current public IP (find with: curl ifconfig.me). Lets your laptop reach the managed DB for the one-time data load."
  type        = string
}
