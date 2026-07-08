# What Terraform prints after `apply` — the values you need for the deploy phase.

output "kubeconfig_command" {
  description = "Run this to point kubectl at the new cloud cluster."
  value       = "doctl kubernetes cluster kubeconfig save ${digitalocean_kubernetes_cluster.cluster.name}"
}

output "registry_endpoint" {
  description = "Tag/push images here, e.g. <endpoint>/macro-rag:v1"
  value       = digitalocean_container_registry.registry.endpoint
}

output "db_host" {
  description = "Managed Postgres host."
  value       = digitalocean_database_cluster.postgres.host
}

output "db_port" {
  value = digitalocean_database_cluster.postgres.port
}

# Full connection URI (includes password) — sensitive, so Terraform masks it.
# View it explicitly with: terraform output -raw db_uri
output "db_uri" {
  description = "Full Postgres URI for the one-time data load (contains the password)."
  value       = digitalocean_database_cluster.postgres.uri
  sensitive   = true
}
