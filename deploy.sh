#!/bin/bash

# Deploy the Cognito Authorization Demo

set -euo pipefail

STACK_NAME="cognito-demo-authorizer-v2"
ENVIRONMENT_NAME="cognito-demo"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="${SCRIPT_DIR}/build"

echo "Deploying Cognito Authorization Demo..."

# Check if AWS CLI is configured
if ! aws sts get-caller-identity > /dev/null 2>&1; then
    echo "Error: AWS CLI not configured. Please run 'aws configure' first."
    exit 1
fi

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-$(aws configure get region || true)}}"
if [ -z "$REGION" ]; then
    echo "Error: No AWS region set. Export AWS_REGION or run 'aws configure'."
    exit 1
fi

# S3 bucket for the packaged Lambda code. Override with ARTIFACT_BUCKET to use your own.
ARTIFACT_BUCKET="${ARTIFACT_BUCKET:-${ENVIRONMENT_NAME}-artifacts-${ACCOUNT_ID}-${REGION}}"

# ---------------------------------------------------------------
# 1. Build the Lambda authorizer package
# ---------------------------------------------------------------
# The authorizer needs PyJWT + cryptography to verify token signatures.
# cryptography ships compiled code, so install wheels built for the
# Lambda runtime (Amazon Linux, x86_64, Python 3.12) rather than for
# this machine.
echo "Building Lambda authorizer package..."
rm -rf "${BUILD_DIR}/authorizer"
mkdir -p "${BUILD_DIR}/authorizer"
python3 -m pip install \
    --quiet \
    --requirement "${SCRIPT_DIR}/lambda/authorizer/requirements.txt" \
    --target "${BUILD_DIR}/authorizer" \
    --platform manylinux2014_x86_64 \
    --implementation cp \
    --python-version 3.12 \
    --only-binary=:all:
cp "${SCRIPT_DIR}/lambda/authorizer/app.py" "${BUILD_DIR}/authorizer/"

# ---------------------------------------------------------------
# 2. Ensure a private artifact bucket exists
# ---------------------------------------------------------------
if ! aws s3api head-bucket --bucket "$ARTIFACT_BUCKET" > /dev/null 2>&1; then
    echo "Creating artifact bucket: ${ARTIFACT_BUCKET}"
    if [ "$REGION" = "us-east-1" ]; then
        aws s3api create-bucket --bucket "$ARTIFACT_BUCKET" --region "$REGION" > /dev/null
    else
        aws s3api create-bucket --bucket "$ARTIFACT_BUCKET" --region "$REGION" \
            --create-bucket-configuration LocationConstraint="$REGION" > /dev/null
    fi
    aws s3api put-public-access-block --bucket "$ARTIFACT_BUCKET" \
        --public-access-block-configuration \
        BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
    aws s3api put-bucket-encryption --bucket "$ARTIFACT_BUCKET" \
        --server-side-encryption-configuration \
        '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
fi

# ---------------------------------------------------------------
# 3. Package and deploy the CloudFormation stack
# ---------------------------------------------------------------
echo "Packaging CloudFormation template..."
aws cloudformation package \
    --template-file "${SCRIPT_DIR}/cloudformation/infrastructure.yaml" \
    --s3-bucket "$ARTIFACT_BUCKET" \
    --output-template-file "${BUILD_DIR}/packaged.yaml"

echo "Deploying CloudFormation stack..."
aws cloudformation deploy \
    --template-file "${BUILD_DIR}/packaged.yaml" \
    --stack-name "$STACK_NAME" \
    --capabilities CAPABILITY_IAM \
    --parameter-overrides EnvironmentName="$ENVIRONMENT_NAME"

# Get stack outputs
echo "Getting stack outputs..."
OUTPUTS=$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" --query 'Stacks[0].Outputs')

USER_POOL_ID=$(echo "$OUTPUTS" | jq -r '.[] | select(.OutputKey=="UserPoolId") | .OutputValue')
CLIENT_ID=$(echo "$OUTPUTS" | jq -r '.[] | select(.OutputKey=="UserPoolClientId") | .OutputValue')
API_URL=$(echo "$OUTPUTS" | jq -r '.[] | select(.OutputKey=="ApiGatewayUrl") | .OutputValue')

echo "Deployment completed successfully!"
echo ""
echo "Stack Information:"
echo "  User Pool ID: ${USER_POOL_ID}"
echo "  Client ID: ${CLIENT_ID}"
echo "  API Gateway URL: ${API_URL}"
echo "  Artifact bucket: ${ARTIFACT_BUCKET}"
echo ""
echo "To test the demo:"
echo "  python3 demo-scripts/test-demo.py"
echo ""
echo "API Endpoints:"
echo "  GET ${API_URL}/users/{userId}         - Get user info"
echo "  GET ${API_URL}/users/{userId}/orders  - Get user orders"
echo "  GET ${API_URL}/users/{userId}/profile - Get user profile"
echo ""
echo "Key Security Features:"
echo "  - Lambda authorizer verifies the JWT signature against the Cognito JWKS"
echo "  - Only access tokens from this user pool and app client are accepted"
echo "  - Users can only access their own data (policy scoped to /users/{sub})"
