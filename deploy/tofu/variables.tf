variable "region" {
  type    = string
  default = "ap-south-1"
}

# Set to 0 to park the GPU node between demo runs. This is the single biggest
# lever on demo cost.
variable "gpu_desired_size" {
  type    = number
  default = 1
}
