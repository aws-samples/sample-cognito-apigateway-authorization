#!/bin/bash

# Cleanup the Cognito Authorization Demo

set -e

echo "🧹 Cleaning up Cognito Authorization Demo..."

STACK_NAME="cognito-demo-authorizer-v2"

# Clean up K8s deployments if they exist
if kubectl get deployments > /dev/null 2>&1; then
    echo "🗑️  Deleting K8s deployments..."
    kubectl delete -f k8s/apis.yaml --ignore-not-found=true
fi

# Check if stack exists
if aws cloudformation describe-stacks --stack-name "$STACK_NAME" > /dev/null 2>&1; then
    echo "📦 Deleting CloudFormation stack: ${STACK_NAME}"
    aws cloudformation delete-stack --stack-name "$STACK_NAME"
    
    echo "⏳ Waiting for stack deletion to complete..."
    aws cloudformation wait stack-delete-complete --stack-name "$STACK_NAME"
    
    echo "✅ Stack deleted successfully!"
else
    echo "ℹ️  Stack ${STACK_NAME} not found or already deleted"
fi

echo "🎉 Cleanup completed!"