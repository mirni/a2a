# AWS Z3 Verifier Lambda — Setup Guide

Step-by-step instructions for deploying the Z3 formal verification Lambda function on AWS from an Ubuntu 24.04 workstation.

---

## Prerequisites

- Ubuntu 24.04 LTS
- Docker installed (for building the container image)
- An AWS account with permissions for Lambda, ECR, IAM, CloudWatch

---

## 1. Install & Configure AWS CLI

```bash
# Install AWS CLI v2
sudo apt-get update && sudo apt-get install -y unzip curl
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o /tmp/awscliv2.zip
unzip -o /tmp/awscliv2.zip -d /tmp/aws-install
sudo /tmp/aws-install/aws/install --update
rm -rf /tmp/awscliv2.zip /tmp/aws-install

# Verify
aws --version
# Expected: aws-cli/2.x.x ...

# Configure credentials (interactive — enter your Access Key, Secret Key, region)
aws configure
# Default region: us-east-1
# Default output: json
```

If using SSO or a profile, replace `aws` with `aws --profile <name>` in all commands below.

---

## 2. Install Docker

Skip if Docker is already installed.

```bash
# Docker official GPG key + repo
sudo apt-get install -y ca-certificates gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin

# Allow current user to run docker without sudo
sudo usermod -aG docker $USER
newgrp docker

# Verify
docker run --rm hello-world
```

---

## 3. Create ECR Repository

```bash
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
AWS_REGION=us-east-1

aws ecr create-repository \
  --repository-name greenhelix/z3-verifier \
  --image-scanning-configuration scanOnPush=true \
  --region $AWS_REGION

# Note the repository URI printed in the output:
# ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/greenhelix/z3-verifier
```

---

## 4. Build & Push the Container Image

```bash
cd lambda/z3-verifier

# Authenticate Docker with ECR
aws ecr get-login-password --region $AWS_REGION | \
  docker login --username AWS --password-stdin ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com

# Build (must be x86_64 — Z3 pip wheel is x86-only)
docker build --platform linux/amd64 -t z3-verifier .

# Tag and push
docker tag z3-verifier:latest \
  ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/greenhelix/z3-verifier:latest

docker push \
  ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/greenhelix/z3-verifier:latest
```

---

## 5. Create IAM Execution Role for Lambda

This role allows the Lambda function to write CloudWatch logs.

```bash
# Create trust policy
cat > /tmp/lambda-trust-policy.json << 'TRUST_EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": { "Service": "lambda.amazonaws.com" },
      "Action": "sts:AssumeRole"
    }
  ]
}
TRUST_EOF

# Create the role
aws iam create-role \
  --role-name z3-verifier-lambda-role \
  --assume-role-policy-document file:///tmp/lambda-trust-policy.json \
  --description "Execution role for the Z3 verifier Lambda function"

# Attach the basic execution policy (CloudWatch Logs only)
aws iam attach-role-policy \
  --role-name z3-verifier-lambda-role \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole

# Get the role ARN (needed for Lambda creation)
LAMBDA_ROLE_ARN=$(aws iam get-role --role-name z3-verifier-lambda-role --query 'Role.Arn' --output text)
echo "Lambda execution role ARN: $LAMBDA_ROLE_ARN"
```

---

## 6. Create the Lambda Function

```bash
# Wait ~10s for IAM role propagation
sleep 10

aws lambda create-function \
  --function-name z3-verifier \
  --package-type Image \
  --code ImageUri=${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/greenhelix/z3-verifier:latest \
  --role $LAMBDA_ROLE_ARN \
  --timeout 900 \
  --memory-size 2048 \
  --architectures x86_64 \
  --environment "Variables={LOG_LEVEL=INFO}" \
  --region $AWS_REGION
```

**Settings rationale:**
- **Timeout 900s** (15min max) — Z3 usually completes in seconds, but complex formulas may take minutes.
- **Memory 2048MB** — allocates ~1 vCPU proportionally. Increase to 4096 if formulas are large.
- **Architecture x86_64** — Z3 pip wheel has no ARM build.

---

## 7. Create a Function URL

Use a Function URL instead of API Gateway — simpler and cheaper for service-to-service calls.

```bash
aws lambda create-function-url-config \
  --function-name z3-verifier \
  --auth-type AWS_IAM \
  --region $AWS_REGION

# Output includes FunctionUrl, e.g.:
# https://<url-id>.lambda-url.us-east-1.on.aws/
```

`AWS_IAM` auth means the gateway must sign requests with SigV4 (via boto3). This is the recommended mode.

---

## 8. Create a Gateway Invoker IAM User

This user has **only** the permission to invoke the Z3 Lambda. The gateway server uses these credentials.

```bash
# Create user
aws iam create-user --user-name a2a-gateway-verifier

# Create a minimal policy: invoke only the z3-verifier function
LAMBDA_ARN=$(aws lambda get-function --function-name z3-verifier --query 'Configuration.FunctionArn' --output text)

cat > /tmp/verifier-invoke-policy.json << POLICY_EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "lambda:InvokeFunction"
      ],
      "Resource": "${LAMBDA_ARN}"
    }
  ]
}
POLICY_EOF

aws iam put-user-policy \
  --user-name a2a-gateway-verifier \
  --policy-name InvokeZ3VerifierOnly \
  --policy-document file:///tmp/verifier-invoke-policy.json

# Create access keys
aws iam create-access-key --user-name a2a-gateway-verifier

# Output includes AccessKeyId and SecretAccessKey — save these securely!
# You'll add them to the gateway's .env file.
```

**Security notes:**
- This user has **zero** other permissions — no S3, no EC2, no IAM admin.
- Rotate these keys periodically via `aws iam create-access-key` + `aws iam delete-access-key`.
- For production, consider using an IAM role with EC2 instance profile instead of static keys.

---

## 9. Test the Lambda

```bash
aws lambda invoke \
  --function-name z3-verifier \
  --payload '{
    "job_id": "test-001",
    "properties": [{
      "name": "simple_sat",
      "language": "z3_smt2",
      "expression": "(declare-const x Int)\n(declare-const y Int)\n(assert (> x 0))\n(assert (< y 10))\n(assert (= (+ x y) 15))"
    }],
    "timeout_seconds": 30
  }' \
  --cli-binary-format raw-in-base64-out \
  /tmp/z3-response.json \
  --region $AWS_REGION

cat /tmp/z3-response.json | python3 -m json.tool
```

Expected output:
```json
{
  "job_id": "test-001",
  "status": "completed",
  "result": "satisfied",
  "property_results": [
    {
      "name": "simple_sat",
      "result": "satisfied",
      "model": "[y = 9, x = 6]"
    }
  ],
  "proof_data": "...",
  "proof_hash": "...",
  "duration_ms": 42
}
```

---

## 10. Configure the Gateway

Add these to the gateway's `.env` file on the server:

```bash
# --- Formal Gatekeeper — AWS Lambda Z3 backend ---
VERIFIER_LAMBDA_FUNCTION=z3-verifier
VERIFIER_LAMBDA_REGION=us-east-1
VERIFIER_AUTH_MODE=iam

# Credentials for the a2a-gateway-verifier IAM user (from step 8)
AWS_ACCESS_KEY_ID=AKIA...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=us-east-1
```

Then install `boto3` on the gateway server:

```bash
pip install boto3
```

And restart the gateway service:

```bash
sudo systemctl restart a2a-gateway
```

---

## 11. CloudWatch Monitoring (Optional)

Lambda logs to CloudWatch automatically. Add an error alarm:

```bash
# Create SNS topic for alerts (skip if you already have one)
aws sns create-topic --name z3-verifier-alerts --region $AWS_REGION
# Subscribe your email:
# aws sns subscribe --topic-arn arn:aws:sns:us-east-1:${AWS_ACCOUNT_ID}:z3-verifier-alerts \
#   --protocol email --notification-endpoint ops@yourcompany.com

aws cloudwatch put-metric-alarm \
  --alarm-name z3-verifier-errors \
  --metric-name Errors \
  --namespace AWS/Lambda \
  --dimensions Name=FunctionName,Value=z3-verifier \
  --statistic Sum \
  --period 300 \
  --threshold 5 \
  --comparison-operator GreaterThanThreshold \
  --evaluation-periods 1 \
  --alarm-actions arn:aws:sns:${AWS_REGION}:${AWS_ACCOUNT_ID}:z3-verifier-alerts \
  --region $AWS_REGION
```

---

## 12. Updating the Lambda

When `handler.py` changes:

```bash
cd lambda/z3-verifier

# Rebuild and push
docker build --platform linux/amd64 -t z3-verifier .
docker tag z3-verifier:latest \
  ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/greenhelix/z3-verifier:latest
docker push \
  ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/greenhelix/z3-verifier:latest

# Update the Lambda to use the new image
aws lambda update-function-code \
  --function-name z3-verifier \
  --image-uri ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/greenhelix/z3-verifier:latest \
  --region $AWS_REGION
```

---

## Cost Estimate

| Usage | Monthly Cost |
|-------|-------------|
| 10 jobs/day, 30s avg, 2GB | ~$0.30/mo |
| 100 jobs/day, 30s avg, 2GB | ~$3/mo |
| CloudWatch Logs (minimal) | ~$0.50/mo |
| ECR storage (~200MB image) | ~$0.02/mo |
| **Total (low usage)** | **< $1/mo** |
| **Total (moderate usage)** | **< $5/mo** |

---

## Teardown

To remove everything:

```bash
# Delete Lambda
aws lambda delete-function --function-name z3-verifier --region $AWS_REGION

# Delete ECR repository (and all images)
aws ecr delete-repository \
  --repository-name greenhelix/z3-verifier \
  --force --region $AWS_REGION

# Delete IAM user and policies
aws iam delete-user-policy --user-name a2a-gateway-verifier --policy-name InvokeZ3VerifierOnly
ACCESS_KEY_ID=$(aws iam list-access-keys --user-name a2a-gateway-verifier --query 'AccessKeyMetadata[0].AccessKeyId' --output text)
aws iam delete-access-key --user-name a2a-gateway-verifier --access-key-id $ACCESS_KEY_ID
aws iam delete-user --user-name a2a-gateway-verifier

# Delete Lambda execution role
aws iam detach-role-policy --role-name z3-verifier-lambda-role \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
aws iam delete-role --role-name z3-verifier-lambda-role
```
