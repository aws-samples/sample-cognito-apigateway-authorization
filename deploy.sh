#!/bin/bash

# Deploy the Cognito Authorization Demo

set -e

echo "Deploying Cognito Authorization Demo..."

# Check if AWS CLI is configured
if ! aws sts get-caller-identity > /dev/null 2>&1; then
    echo "Error: AWS CLI not configured. Please run 'aws configure' first."
    exit 1
fi

# Deploy CloudFormation stack
echo "Deploying CloudFormation stack..."
aws cloudformation deploy \
    --template-file cloudformation/infrastructure.yaml \
    --stack-name cognito-demo-authorizer-v2 \
    --capabilities CAPABILITY_IAM \
    --parameter-overrides ProjectName=cognito-demo

# Get stack outputs
echo "Getting stack outputs..."
OUTPUTS=$(aws cloudformation describe-stacks --stack-name cognito-demo-authorizer-v2 --query 'Stacks[0].Outputs')

USER_POOL_ID=$(echo $OUTPUTS | jq -r '.[] | select(.OutputKey=="UserPoolId") | .OutputValue')
CLIENT_ID=$(echo $OUTPUTS | jq -r '.[] | select(.OutputKey=="UserPoolClientId") | .OutputValue')
API_URL=$(echo $OUTPUTS | jq -r '.[] | select(.OutputKey=="ApiGatewayUrl") | .OutputValue')

echo "Deployment completed successfully!"
echo ""
echo "Stack Information:"
echo "  User Pool ID: $USER_POOL_ID"
echo "  Client ID: $CLIENT_ID"
echo "  API Gateway URL: $API_URL"
echo ""
echo "To test the demo:"
echo "  python3 demo-scripts/test-demo.py"
echo ""
echo "API Endpoints:"
echo "  GET $API_URL/users/{userId}         - Get user info"
echo "  GET $API_URL/users/{userId}/orders  - Get user orders"
echo "  GET $API_URL/users/{userId}/profile - Get user profile"
echo ""
echo "Key Security Features:"
echo "  - Users can only access their own data (sub claim validation)"
echo "  - Lambda authorizer validates JWT tokens"
echo "  - Fine-grained authorization with user-agent restrictions"
echo "  - Automatic denial for cross-user data access attempts"