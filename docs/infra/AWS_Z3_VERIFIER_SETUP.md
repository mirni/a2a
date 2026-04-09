# AWS Z3 Verifier Lambda — Setup Guide

Complete guide for deploying the Z3 formal verification Lambda on AWS, starting from a fresh AWS account on Ubuntu 24.04.

---

## Quick Start (Experienced Users)

If you already have AWS CLI + Docker configured:

```bash
scripts/deploy_z3_verifier.sh              # deploy everything
scripts/deploy_z3_verifier.sh --teardown   # remove everything
```

The script is idempotent — safe to re-run. See options with `--help`.

---

## Part 1: AWS Account Setup (From Scratch)

### 1.1 Create an AWS Account

1. Go to https://aws.amazon.com/ and click **Create an AWS Account**
2. Enter email, password, and account name (e.g. `greenhelix-prod`)
3. Choose **Personal** or **Business** account type
4. Enter payment method (credit card required even for Free Tier)
5. Complete phone verification
6. Select the **Basic Support — Free** plan

**Free Tier note:** A new AWS account gets 12 months of Free Tier. The Z3 verifier stays well within free limits:
- Lambda: 1M free requests + 400,000 GB-seconds/month (we use ~1,000 requests at 2GB)
- ECR: 500MB free storage (our image is ~200MB)
- CloudWatch: 10 custom alarms free, 5GB log ingestion free

**After Free Tier expires**, expect < $5/month at moderate usage (see cost table below).

### 1.2 Secure the Root Account

Do this immediately after account creation:

1. **Enable MFA on root**: AWS Console → IAM → Security credentials → Assign MFA device → Use an authenticator app (Google Authenticator, Authy, etc.)
2. **Create an admin IAM user** (never use root for daily work):

```bash
# After installing AWS CLI (step 2.1), run these as root:
aws iam create-user --user-name admin

aws iam attach-user-policy \
    --user-name admin \
    --policy-arn arn:aws:iam::aws:policy/AdministratorAccess

aws iam create-access-key --user-name admin
# Save the AccessKeyId and SecretAccessKey

aws iam create-login-profile \
    --user-name admin \
    --password 'YourSecurePasswordHere!' \
    --password-reset-required
```

3. **Enable MFA on the admin user** too: Console → IAM → Users → admin → Security credentials → Assign MFA

4. **Set up a billing alarm** to avoid surprise charges:
   - Console → Billing → Billing preferences → Enable **Free Tier usage alerts**
   - Console → CloudWatch → Alarms → Create alarm:
     - Metric: `AWS/Billing` → `EstimatedCharges` → `Currency: USD`
     - Threshold: `> $10` (or whatever your comfort level is)
     - Notify via email

### 1.3 Required IAM Permissions

The deployment script needs an IAM user/role with these permissions. The `AdministratorAccess` policy covers all of them, but if you prefer least-privilege for the deployer, create a custom policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ECRAuth",
      "Effect": "Allow",
      "Action": "ecr:GetAuthorizationToken",
      "Resource": "*"
    },
    {
      "Sid": "ECRRepo",
      "Effect": "Allow",
      "Action": [
        "ecr:CreateRepository",
        "ecr:DescribeRepositories",
        "ecr:DeleteRepository",
        "ecr:BatchCheckLayerAvailability",
        "ecr:InitiateLayerUpload",
        "ecr:UploadLayerPart",
        "ecr:CompleteLayerUpload",
        "ecr:PutImage"
      ],
      "Resource": "arn:aws:ecr:*:*:repository/greenhelix/z3-verifier"
    },
    {
      "Sid": "Lambda",
      "Effect": "Allow",
      "Action": [
        "lambda:CreateFunction",
        "lambda:UpdateFunctionCode",
        "lambda:GetFunction",
        "lambda:DeleteFunction",
        "lambda:CreateFunctionUrlConfig",
        "lambda:GetFunctionUrlConfig",
        "lambda:InvokeFunction"
      ],
      "Resource": "arn:aws:lambda:*:*:function:z3-verifier"
    },
    {
      "Sid": "IAMRoles",
      "Effect": "Allow",
      "Action": [
        "iam:CreateRole",
        "iam:DeleteRole",
        "iam:GetRole",
        "iam:AttachRolePolicy",
        "iam:DetachRolePolicy"
      ],
      "Resource": "arn:aws:iam::*:role/z3-verifier-lambda-role"
    },
    {
      "Sid": "IAMPassRole",
      "Effect": "Allow",
      "Action": "iam:PassRole",
      "Resource": "arn:aws:iam::*:role/z3-verifier-lambda-role",
      "Condition": {
        "StringEquals": {
          "iam:PassedToService": "lambda.amazonaws.com"
        }
      }
    },
    {
      "Sid": "IAMUsers",
      "Effect": "Allow",
      "Action": [
        "iam:CreateUser",
        "iam:DeleteUser",
        "iam:GetUser",
        "iam:PutUserPolicy",
        "iam:DeleteUserPolicy",
        "iam:CreateAccessKey",
        "iam:DeleteAccessKey",
        "iam:ListAccessKeys"
      ],
      "Resource": "arn:aws:iam::*:user/a2a-gateway-verifier"
    },
    {
      "Sid": "CloudWatch",
      "Effect": "Allow",
      "Action": [
        "cloudwatch:PutMetricAlarm",
        "cloudwatch:DeleteAlarms"
      ],
      "Resource": "*"
    },
    {
      "Sid": "SNS",
      "Effect": "Allow",
      "Action": [
        "sns:CreateTopic",
        "sns:Subscribe"
      ],
      "Resource": "*"
    },
    {
      "Sid": "STS",
      "Effect": "Allow",
      "Action": "sts:GetCallerIdentity",
      "Resource": "*"
    }
  ]
}
```

To attach it:

```bash
# Save the JSON above to /tmp/z3-deployer-policy.json, then:
aws iam create-policy \
    --policy-name Z3VerifierDeployerPolicy \
    --policy-document file:///tmp/z3-deployer-policy.json

# Attach to your deployer user:
aws iam attach-user-policy \
    --user-name admin \
    --policy-arn arn:aws:iam::<ACCOUNT_ID>:policy/Z3VerifierDeployerPolicy
```

### 1.4 Billing Expectations

| Component | Free Tier (12 months) | After Free Tier |
|-----------|----------------------|-----------------|
| Lambda (1M req + 400K GB-s) | $0.00 | ~$0.30/mo at 10 jobs/day |
| ECR (500MB storage) | $0.00 | ~$0.02/mo for 200MB image |
| CloudWatch Logs (5GB) | $0.00 | ~$0.50/mo |
| CloudWatch Alarms (10 free) | $0.00 | $0.10/alarm/mo |
| **Total** | **$0.00** | **< $1–5/mo** |

No upfront costs. No reserved capacity. Pay only for what you use.

---

## Part 2: Workstation Setup (Ubuntu 24.04)

### 2.1 Install AWS CLI

```bash
sudo apt-get update && sudo apt-get install -y unzip curl

curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o /tmp/awscliv2.zip
unzip -o /tmp/awscliv2.zip -d /tmp/aws-install
sudo /tmp/aws-install/aws/install --update
rm -rf /tmp/awscliv2.zip /tmp/aws-install

aws --version   # aws-cli/2.x.x
```

### 2.2 Configure AWS Credentials

```bash
aws configure
# AWS Access Key ID:     <from step 1.2>
# AWS Secret Access Key: <from step 1.2>
# Default region:        us-east-1
# Default output format: json

# Verify:
aws sts get-caller-identity
```

If using AWS SSO or named profiles, set `AWS_PROFILE` before running the deploy script:
```bash
export AWS_PROFILE=my-profile
```

### 2.3 Install Docker

```bash
# Add Docker's official GPG key and repo
sudo apt-get install -y ca-certificates gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | \
    sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo "deb [arch=$(dpkg --print-architecture) \
    signed-by=/etc/apt/keyrings/docker.gpg] \
    https://download.docker.com/linux/ubuntu \
    $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
    sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin

# Allow your user to run Docker without sudo
sudo usermod -aG docker $USER
newgrp docker

# Verify
docker run --rm hello-world
```

---

## Part 3: Deploy

### 3.1 One-Command Deploy

From the repository root:

```bash
scripts/deploy_z3_verifier.sh
```

This will:
1. Create the ECR repository (if it doesn't exist)
2. Build the Docker image (x86_64) and push to ECR
3. Create the Lambda execution IAM role (CloudWatch Logs only)
4. Create the Lambda function (or update code if it exists)
5. Create a Function URL with IAM auth
6. Create the gateway invoker IAM user with least-privilege policy
7. Set up a CloudWatch error alarm
8. Run a smoke test to verify everything works
9. Print the `.env` config for the gateway

**Save the access keys printed in step 6** — they are shown only once.

### 3.2 Script Options

```bash
# Use a different region
scripts/deploy_z3_verifier.sh --region eu-west-1

# Increase memory for complex formulas
scripts/deploy_z3_verifier.sh --memory 4096

# Skip Docker build (use existing image in ECR)
scripts/deploy_z3_verifier.sh --skip-docker

# Skip CloudWatch alarm
scripts/deploy_z3_verifier.sh --skip-monitoring

# Add email alerts
SNS_ALERT_EMAIL=ops@example.com scripts/deploy_z3_verifier.sh

# Preview without executing
scripts/deploy_z3_verifier.sh --dry-run

# Remove everything
scripts/deploy_z3_verifier.sh --teardown
```

### 3.3 Configure the Gateway

After deployment, add these to the gateway server's `.env`:

```bash
# --- Formal Gatekeeper — AWS Lambda Z3 backend ---
VERIFIER_LAMBDA_FUNCTION=z3-verifier
VERIFIER_LAMBDA_REGION=us-east-1
VERIFIER_AUTH_MODE=iam

# Credentials for the a2a-gateway-verifier IAM user
AWS_ACCESS_KEY_ID=AKIA...         # from deploy output
AWS_SECRET_ACCESS_KEY=...         # from deploy output
AWS_REGION=us-east-1
```

Install boto3 and restart:

```bash
pip install boto3
sudo systemctl restart a2a-gateway
```

### 3.4 Manual Smoke Test

```bash
aws lambda invoke \
    --function-name z3-verifier \
    --payload '{
        "job_id": "manual-test",
        "properties": [{
            "name": "balance_check",
            "language": "z3_smt2",
            "expression": "(declare-const x Int)\n(declare-const y Int)\n(assert (> x 0))\n(assert (< y 10))\n(assert (= (+ x y) 15))"
        }],
        "timeout_seconds": 30
    }' \
    --cli-binary-format raw-in-base64-out \
    /tmp/z3-test.json \
    --region us-east-1

python3 -m json.tool /tmp/z3-test.json
```

Expected: `"result": "satisfied"` with a model like `[y = 9, x = 6]`.

---

## Part 4: Updating the Lambda

When `lambda/z3-verifier/handler.py` changes, re-run the deploy script:

```bash
scripts/deploy_z3_verifier.sh
```

It detects the existing function and updates the code (skipping IAM/ECR creation).

Or update just the image manually:

```bash
cd lambda/z3-verifier
docker build --platform linux/amd64 -t z3-verifier .
docker tag z3-verifier:latest <ECR_URI>:latest
docker push <ECR_URI>:latest
aws lambda update-function-code \
    --function-name z3-verifier \
    --image-uri <ECR_URI>:latest \
    --region us-east-1
```

---

## Part 5: Architecture & Security Notes

### What Gets Created

| Resource | Name | Purpose |
|----------|------|---------|
| ECR Repository | `greenhelix/z3-verifier` | Stores the Docker image |
| IAM Role | `z3-verifier-lambda-role` | Lambda execution (CloudWatch Logs only) |
| Lambda Function | `z3-verifier` | Runs Z3 solver (2GB RAM, 15min timeout) |
| Function URL | `https://<id>.lambda-url...` | Direct HTTPS endpoint (IAM auth) |
| IAM User | `a2a-gateway-verifier` | Gateway's credentials (invoke-only) |
| CloudWatch Alarm | `z3-verifier-errors` | Alerts on > 5 errors in 5 minutes |
| SNS Topic | `z3-verifier-alerts` | Alert delivery |

### Security Model

- **Lambda execution role**: Can ONLY write CloudWatch Logs. No S3, no network, no other AWS access.
- **Gateway invoker user**: Can ONLY call `lambda:InvokeFunction` on the `z3-verifier` function. Zero other permissions.
- **Function URL auth**: `AWS_IAM` — requests must be signed with SigV4. No public access.
- **ECR image scanning**: Enabled — AWS scans for CVEs on every push.
- **No VPC required**: Lambda runs in AWS-managed networking. Z3 has no outbound dependencies.

### Why Lambda vs EC2/ECS

- **Cost**: Lambda is free at low volumes, pennies at moderate. An EC2 instance costs ~$30+/mo even idle.
- **Scaling**: Lambda scales to 1000 concurrent executions automatically. No capacity planning.
- **Operations**: No OS patching, no uptime monitoring, no SSH access to manage.
- **Cold starts**: ~2-5 seconds for the first invocation. Subsequent calls are warm (~100ms). Acceptable for verification jobs that take seconds anyway.

---

## Teardown

Remove all AWS resources:

```bash
scripts/deploy_z3_verifier.sh --teardown
```

Or manually:

```bash
AWS_REGION=us-east-1

aws lambda delete-function --function-name z3-verifier --region $AWS_REGION

aws ecr delete-repository --repository-name greenhelix/z3-verifier --force --region $AWS_REGION

aws iam delete-user-policy --user-name a2a-gateway-verifier --policy-name InvokeZ3VerifierOnly
KEY_ID=$(aws iam list-access-keys --user-name a2a-gateway-verifier \
    --query 'AccessKeyMetadata[0].AccessKeyId' --output text)
aws iam delete-access-key --user-name a2a-gateway-verifier --access-key-id $KEY_ID
aws iam delete-user --user-name a2a-gateway-verifier

aws iam detach-role-policy --role-name z3-verifier-lambda-role \
    --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
aws iam delete-role --role-name z3-verifier-lambda-role

aws cloudwatch delete-alarms --alarm-names z3-verifier-errors --region $AWS_REGION
```
