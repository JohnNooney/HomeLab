# Remote state backend — bootstrapping order:
#   1. Deploy with local state first:  terraform apply -target=module.state_backend
#   2. Uncomment the block below, filling in the bucket name from the output
#   3. Run: terraform init -migrate-state  (this migrates local state → S3)

 terraform {
   backend "s3" {
     bucket         = "homelab-terraform-state-365070926463"
     key            = "aws/terraform.tfstate"
     region         = "eu-west-2"
     use_lockfile   = true
     encrypt        = true
   }
 }
