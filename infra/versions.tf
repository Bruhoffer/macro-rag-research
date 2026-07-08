# Pins Terraform + the DigitalOcean provider so `apply` is reproducible.
terraform {
  required_version = ">= 1.6"
  required_providers {
    digitalocean = {
      source  = "digitalocean/digitalocean"
      version = "~> 2.40"
    }
  }
}

# The provider authenticates with your DO API token. Never hardcode it here —
# it comes from var.do_token (see variables.tf), which you supply via a gitignored
# terraform.tfvars or the TF_VAR_do_token environment variable.
provider "digitalocean" {
  token = var.do_token
}
