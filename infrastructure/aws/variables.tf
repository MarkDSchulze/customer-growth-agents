variable "name" {
  type    = string
  default = "customer-growth"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,30}$", var.name))
    error_message = "Use a lowercase project name with 3-31 characters."
  }
}
variable "region" {
  type    = string
  default = "us-east-1"
  validation {
    condition     = contains(["us-east-1", "eu-west-1", "ap-southeast-2"], var.region)
    error_message = "Choose a region supported by the regional application contract."
  }
}
variable "vpc_id" { type = string }
variable "private_subnet_ids" {
  type = list(string)
  validation {
    condition     = length(distinct(var.private_subnet_ids)) >= 3
    error_message = "Supply private subnets in at least three availability zones."
  }
}
variable "kubernetes_version" {
  type    = string
  default = "1.34"
}
variable "instance_types" {
  type    = list(string)
  default = ["m7i.large"]
}
variable "namespace" {
  type    = string
  default = "growth"
}
variable "min_nodes" {
  type    = number
  default = 3
  validation {
    condition     = var.min_nodes >= 3
    error_message = "The regional foundation requires at least three nodes."
  }
}
variable "max_nodes" {
  type    = number
  default = 12
  validation {
    condition     = var.max_nodes >= var.min_nodes
    error_message = "max_nodes must be at least min_nodes."
  }
}
