# ═══════════════════════════════════════════════════════════════════
# The cloud versions of everything you ran locally:
#   local Docker Desktop cluster  → DOKS (managed Kubernetes)
#   local Postgres container       → DO Managed Postgres (pgvector)
#   local Docker daemon            → DO Container Registry
# ═══════════════════════════════════════════════════════════════════

# Ask DO for the latest supported Kubernetes version instead of hardcoding a slug.
data "digitalocean_kubernetes_versions" "current" {}

# ── The Kubernetes cluster (your workers) ──────────────────────────
resource "digitalocean_kubernetes_cluster" "cluster" {
  name    = var.name
  region  = var.region
  version = data.digitalocean_kubernetes_versions.current.latest_version

  node_pool {
    name       = "${var.name}-workers"
    size       = var.node_size
    node_count = var.node_count
  }
}

# ── Managed Postgres (replaces host.docker.internal:5433) ──────────
resource "digitalocean_database_cluster" "postgres" {
  name       = "${var.name}-db"
  engine     = "pg"
  version    = var.pg_version
  size       = var.db_size
  region     = var.region
  node_count = 1
}

# Lock the DB down: only the K8s cluster and your laptop's IP may connect.
resource "digitalocean_database_firewall" "postgres" {
  cluster_id = digitalocean_database_cluster.postgres.id

  rule {
    type  = "k8s" # the whole cluster's nodes, by cluster UUID
    value = digitalocean_kubernetes_cluster.cluster.id
  }
  rule {
    type  = "ip_addr" # your laptop, for the one-time data load
    value = var.my_ip
  }
}

# ── Container registry (the pod pulls its image from here) ─────────
resource "digitalocean_container_registry" "registry" {
  name                   = var.registry_name
  subscription_tier_slug = "basic" # 5 GB — our image is ~586 MB, over the free 500 MB tier
  region                 = var.region
}

# Let the cluster pull private images from the registry (wires registry creds into K8s).
resource "digitalocean_container_registry_docker_credentials" "creds" {
  registry_name = digitalocean_container_registry.registry.name
}
