#!/usr/bin/env bash
# =============================================================================
# Z3 Verifier Lambda — Automated AWS Deployment
# =============================================================================
# Deploys the Z3 formal verification Lambda function to AWS. Handles ECR repo
# creation, Docker image build/push, IAM roles, Lambda creation, Function URL,
# and gateway invoker user — all idempotent (safe to re-run).
#
# Usage:
#   scripts/deploy_z3_verifier.sh [OPTIONS]
#
# Options:
#   --region <region>       AWS region (default: us-east-1)
#   --memory <mb>           Lambda memory in MB (default: 2048)
#   --timeout <seconds>     Lambda timeout in seconds (default: 900)
#   --skip-docker           Skip Docker build/push (use existing image)
#   --skip-monitoring       Skip CloudWatch alarm creation
#   --teardown              Remove all resources instead of creating them
#   --dry-run               Print commands without executing
#   -h, --help              Show help
#
# Prerequisites:
#   - AWS CLI v2 configured (aws configure)
#   - Docker installed and running
#   - Run from repository root (lambda/z3-verifier/ must exist)
#
# Environment variable overrides:
#   AWS_REGION, LAMBDA_MEMORY_MB, LAMBDA_TIMEOUT_S, SNS_ALERT_EMAIL
#
# See docs/infra/AWS_Z3_VERIFIER_SETUP.md for full walkthrough.
# =============================================================================

set -euo pipefail

# ---- Defaults ---------------------------------------------------------------

REGION="${AWS_REGION:-us-east-1}"
MEMORY="${LAMBDA_MEMORY_MB:-2048}"
TIMEOUT="${LAMBDA_TIMEOUT_S:-900}"
FUNCTION_NAME="z3-verifier"
ECR_REPO="greenhelix/z3-verifier"
LAMBDA_ROLE_NAME="z3-verifier-lambda-role"
INVOKER_USER="a2a-gateway-verifier"
INVOKER_POLICY="InvokeZ3VerifierOnly"
ALARM_NAME="z3-verifier-errors"
SNS_TOPIC="z3-verifier-alerts"
ALERT_EMAIL="${SNS_ALERT_EMAIL:-}"

SKIP_DOCKER=false
SKIP_MONITORING=false
TEARDOWN=false
DRY_RUN=false

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LAMBDA_DIR="$REPO_ROOT/lambda/z3-verifier"

# ---- Colors -----------------------------------------------------------------

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log()  { echo -e "${GREEN}[+]${NC} $*"; }
warn() { echo -e "${YELLOW}[!]${NC} $*"; }
err()  { echo -e "${RED}[ERROR]${NC} $*" >&2; }
info() { echo -e "${CYAN}[i]${NC} $*"; }

# ---- Argument parsing -------------------------------------------------------

usage() {
    awk '/^# =====/{n++; next} n==2{sub(/^# ?/,""); print} n>=3{exit}' "$0"
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --region)       REGION="$2"; shift 2 ;;
        --memory)       MEMORY="$2"; shift 2 ;;
        --timeout)      TIMEOUT="$2"; shift 2 ;;
        --skip-docker)  SKIP_DOCKER=true; shift ;;
        --skip-monitoring) SKIP_MONITORING=true; shift ;;
        --teardown)     TEARDOWN=true; shift ;;
        --dry-run)      DRY_RUN=true; shift ;;
        -h|--help)      usage ;;
        *)              err "Unknown option: $1"; usage ;;
    esac
done

# ---- Helpers ----------------------------------------------------------------

run() {
    if $DRY_RUN; then
        echo "  [dry-run] $*"
    else
        "$@"
    fi
}

aws_exists() {
    # Returns 0 if the AWS resource exists (command succeeds), 1 otherwise
    "$@" >/dev/null 2>&1
}

# ---- Preflight --------------------------------------------------------------

preflight() {
    log "Preflight checks..."

    if ! command -v aws &>/dev/null; then
        err "AWS CLI not found. Install: https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html"
        exit 1
    fi

    if ! $SKIP_DOCKER && ! command -v docker &>/dev/null; then
        err "Docker not found. Install: https://docs.docker.com/engine/install/ubuntu/"
        exit 1
    fi

    if ! aws sts get-caller-identity &>/dev/null; then
        err "AWS credentials not configured. Run: aws configure"
        exit 1
    fi

    AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
    ECR_URI="${AWS_ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${ECR_REPO}"
    IMAGE_URI="${ECR_URI}:latest"

    info "Account:  $AWS_ACCOUNT_ID"
    info "Region:   $REGION"
    info "ECR URI:  $ECR_URI"

    if ! $SKIP_DOCKER && [[ ! -f "$LAMBDA_DIR/Dockerfile" ]]; then
        err "Dockerfile not found at $LAMBDA_DIR/Dockerfile"
        err "Run this script from the repository root."
        exit 1
    fi
}

# =============================================================================
# TEARDOWN
# =============================================================================

teardown() {
    preflight
    warn "Tearing down ALL Z3 verifier resources in $REGION..."
    echo ""

    # Lambda function
    if aws_exists aws lambda get-function --function-name "$FUNCTION_NAME" --region "$REGION"; then
        log "Deleting Lambda function: $FUNCTION_NAME"
        run aws lambda delete-function --function-name "$FUNCTION_NAME" --region "$REGION"
    else
        info "Lambda function $FUNCTION_NAME does not exist — skipping"
    fi

    # ECR repository
    if aws_exists aws ecr describe-repositories --repository-names "$ECR_REPO" --region "$REGION"; then
        log "Deleting ECR repository: $ECR_REPO (and all images)"
        run aws ecr delete-repository --repository-name "$ECR_REPO" --force --region "$REGION"
    else
        info "ECR repo $ECR_REPO does not exist — skipping"
    fi

    # Gateway invoker user
    if aws_exists aws iam get-user --user-name "$INVOKER_USER"; then
        log "Deleting IAM user: $INVOKER_USER"
        # Delete inline policy
        run aws iam delete-user-policy --user-name "$INVOKER_USER" --policy-name "$INVOKER_POLICY" 2>/dev/null || true
        # Delete all access keys
        for key_id in $(aws iam list-access-keys --user-name "$INVOKER_USER" --query 'AccessKeyMetadata[].AccessKeyId' --output text 2>/dev/null); do
            run aws iam delete-access-key --user-name "$INVOKER_USER" --access-key-id "$key_id"
        done
        run aws iam delete-user --user-name "$INVOKER_USER"
    else
        info "IAM user $INVOKER_USER does not exist — skipping"
    fi

    # Lambda execution role
    if aws_exists aws iam get-role --role-name "$LAMBDA_ROLE_NAME"; then
        log "Deleting IAM role: $LAMBDA_ROLE_NAME"
        run aws iam detach-role-policy --role-name "$LAMBDA_ROLE_NAME" \
            --policy-arn "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole" 2>/dev/null || true
        run aws iam delete-role --role-name "$LAMBDA_ROLE_NAME"
    else
        info "IAM role $LAMBDA_ROLE_NAME does not exist — skipping"
    fi

    # CloudWatch alarm
    if ! $SKIP_MONITORING; then
        log "Deleting CloudWatch alarm: $ALARM_NAME"
        run aws cloudwatch delete-alarms --alarm-names "$ALARM_NAME" --region "$REGION" 2>/dev/null || true
    fi

    echo ""
    log "Teardown complete."
}

# =============================================================================
# DEPLOY
# =============================================================================

create_ecr_repo() {
    if aws_exists aws ecr describe-repositories --repository-names "$ECR_REPO" --region "$REGION"; then
        info "ECR repository already exists: $ECR_REPO"
    else
        log "Creating ECR repository: $ECR_REPO"
        run aws ecr create-repository \
            --repository-name "$ECR_REPO" \
            --image-scanning-configuration scanOnPush=true \
            --region "$REGION"
    fi
}

build_and_push_image() {
    if $SKIP_DOCKER; then
        info "Skipping Docker build/push (--skip-docker)"
        return
    fi

    log "Authenticating Docker with ECR..."
    aws ecr get-login-password --region "$REGION" | \
        docker login --username AWS --password-stdin \
        "${AWS_ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"

    log "Building container image (x86_64)..."
    run docker build --platform linux/amd64 -t z3-verifier "$LAMBDA_DIR"

    log "Tagging and pushing to ECR..."
    run docker tag z3-verifier:latest "$IMAGE_URI"
    run docker push "$IMAGE_URI"
}

create_lambda_role() {
    if aws_exists aws iam get-role --role-name "$LAMBDA_ROLE_NAME"; then
        info "Lambda execution role already exists: $LAMBDA_ROLE_NAME"
        LAMBDA_ROLE_ARN=$(aws iam get-role --role-name "$LAMBDA_ROLE_NAME" --query 'Role.Arn' --output text)
    else
        log "Creating Lambda execution role: $LAMBDA_ROLE_NAME"
        local trust_policy
        trust_policy=$(cat <<'EOF'
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
EOF
)
        run aws iam create-role \
            --role-name "$LAMBDA_ROLE_NAME" \
            --assume-role-policy-document "$trust_policy" \
            --description "Execution role for the Z3 verifier Lambda function"

        run aws iam attach-role-policy \
            --role-name "$LAMBDA_ROLE_NAME" \
            --policy-arn "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"

        LAMBDA_ROLE_ARN=$(aws iam get-role --role-name "$LAMBDA_ROLE_NAME" --query 'Role.Arn' --output text)

        # IAM propagation delay
        log "Waiting 10s for IAM role propagation..."
        sleep 10
    fi
    info "Role ARN: $LAMBDA_ROLE_ARN"
}

create_lambda_function() {
    if aws_exists aws lambda get-function --function-name "$FUNCTION_NAME" --region "$REGION"; then
        info "Lambda function already exists — updating code..."
        run aws lambda update-function-code \
            --function-name "$FUNCTION_NAME" \
            --image-uri "$IMAGE_URI" \
            --region "$REGION"
    else
        log "Creating Lambda function: $FUNCTION_NAME"
        run aws lambda create-function \
            --function-name "$FUNCTION_NAME" \
            --package-type Image \
            --code "ImageUri=$IMAGE_URI" \
            --role "$LAMBDA_ROLE_ARN" \
            --timeout "$TIMEOUT" \
            --memory-size "$MEMORY" \
            --architectures x86_64 \
            --environment "Variables={LOG_LEVEL=INFO}" \
            --region "$REGION"
    fi
}

create_function_url() {
    if aws lambda get-function-url-config --function-name "$FUNCTION_NAME" --region "$REGION" &>/dev/null; then
        info "Function URL already configured"
    else
        log "Creating Function URL (auth: AWS_IAM)..."
        run aws lambda create-function-url-config \
            --function-name "$FUNCTION_NAME" \
            --auth-type AWS_IAM \
            --region "$REGION"
    fi

    FUNCTION_URL=$(aws lambda get-function-url-config \
        --function-name "$FUNCTION_NAME" \
        --region "$REGION" \
        --query 'FunctionUrl' --output text 2>/dev/null || echo "N/A")
    info "Function URL: $FUNCTION_URL"
}

create_gateway_invoker() {
    if aws_exists aws iam get-user --user-name "$INVOKER_USER"; then
        info "Gateway invoker user already exists: $INVOKER_USER"
        return
    fi

    log "Creating gateway invoker IAM user: $INVOKER_USER"
    run aws iam create-user --user-name "$INVOKER_USER"

    LAMBDA_ARN=$(aws lambda get-function --function-name "$FUNCTION_NAME" \
        --query 'Configuration.FunctionArn' --output text --region "$REGION")

    local invoke_policy
    invoke_policy=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["lambda:InvokeFunction"],
      "Resource": "${LAMBDA_ARN}"
    }
  ]
}
EOF
)

    run aws iam put-user-policy \
        --user-name "$INVOKER_USER" \
        --policy-name "$INVOKER_POLICY" \
        --policy-document "$invoke_policy"

    log "Creating access keys for $INVOKER_USER..."
    echo ""
    echo "============================================================"
    echo "  SAVE THESE CREDENTIALS — they are shown only once!"
    echo "============================================================"
    aws iam create-access-key --user-name "$INVOKER_USER"
    echo "============================================================"
    echo ""
    warn "Add these to the gateway .env file as AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY"
}

setup_monitoring() {
    if $SKIP_MONITORING; then
        info "Skipping monitoring setup (--skip-monitoring)"
        return
    fi

    log "Setting up CloudWatch error alarm..."

    # Create SNS topic (idempotent)
    SNS_ARN=$(aws sns create-topic --name "$SNS_TOPIC" --region "$REGION" \
        --query 'TopicArn' --output text)

    if [[ -n "$ALERT_EMAIL" ]]; then
        log "Subscribing $ALERT_EMAIL to alerts..."
        run aws sns subscribe \
            --topic-arn "$SNS_ARN" \
            --protocol email \
            --notification-endpoint "$ALERT_EMAIL" \
            --region "$REGION"
        warn "Check your email and confirm the SNS subscription."
    fi

    run aws cloudwatch put-metric-alarm \
        --alarm-name "$ALARM_NAME" \
        --metric-name Errors \
        --namespace AWS/Lambda \
        --dimensions "Name=FunctionName,Value=$FUNCTION_NAME" \
        --statistic Sum \
        --period 300 \
        --threshold 5 \
        --comparison-operator GreaterThanThreshold \
        --evaluation-periods 1 \
        --alarm-actions "$SNS_ARN" \
        --region "$REGION"
}

smoke_test() {
    log "Running smoke test..."
    local output_file="/tmp/z3-verifier-smoke-test.json"

    aws lambda invoke \
        --function-name "$FUNCTION_NAME" \
        --payload '{
            "job_id": "smoke-test",
            "properties": [{
                "name": "simple_sat",
                "language": "z3_smt2",
                "expression": "(declare-const x Int)\n(declare-const y Int)\n(assert (> x 0))\n(assert (< y 10))\n(assert (= (+ x y) 15))"
            }],
            "timeout_seconds": 30
        }' \
        --cli-binary-format raw-in-base64-out \
        "$output_file" \
        --region "$REGION" >/dev/null

    local result
    result=$(python3 -c "import json; print(json.load(open('$output_file'))['result'])" 2>/dev/null || echo "PARSE_ERROR")

    if [[ "$result" == "satisfied" ]]; then
        log "Smoke test PASSED (result: satisfied)"
    else
        err "Smoke test FAILED (result: $result)"
        echo "Response:"
        python3 -m json.tool "$output_file" 2>/dev/null || cat "$output_file"
        return 1
    fi
}

print_gateway_config() {
    echo ""
    echo "============================================================"
    echo "  Gateway .env configuration"
    echo "============================================================"
    echo ""
    echo "  VERIFIER_LAMBDA_FUNCTION=$FUNCTION_NAME"
    echo "  VERIFIER_LAMBDA_REGION=$REGION"
    echo "  VERIFIER_AUTH_MODE=iam"
    echo "  AWS_ACCESS_KEY_ID=<from step above>"
    echo "  AWS_SECRET_ACCESS_KEY=<from step above>"
    echo "  AWS_REGION=$REGION"
    echo ""
    echo "============================================================"
}

deploy() {
    preflight
    log "Deploying Z3 verifier Lambda to $REGION..."
    echo ""

    create_ecr_repo
    build_and_push_image
    create_lambda_role
    create_lambda_function
    create_function_url
    create_gateway_invoker
    setup_monitoring
    smoke_test
    print_gateway_config

    echo ""
    log "Deployment complete!"
}

# ---- Main -------------------------------------------------------------------

if $TEARDOWN; then
    teardown
else
    deploy
fi
