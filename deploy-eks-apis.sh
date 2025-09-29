#!/bin/bash

# Deploy APIs to EKS cluster

set -e

echo "🚀 Deploying APIs to EKS cluster..."

# Get EKS cluster name from CloudFormation
CLUSTER_NAME=$(aws cloudformation describe-stacks --stack-name cognito-demo-authorizer-v2 --query 'Stacks[0].Outputs[?OutputKey==`EKSClusterName`].OutputValue' --output text)

if [ -z "$CLUSTER_NAME" ]; then
    echo "❌ EKS cluster not found. Deploy CloudFormation stack first."
    exit 1
fi

echo "📋 Using EKS cluster: $CLUSTER_NAME"

# Update kubeconfig
echo "🔧 Updating kubeconfig..."
aws eks update-kubeconfig --name $CLUSTER_NAME

# Deploy the 3 APIs
echo "📦 Deploying APIs to EKS..."
kubectl apply -f k8s/apis.yaml

# Wait for deployments
echo "⏳ Waiting for deployments..."
kubectl wait --for=condition=available --timeout=300s deployment/user-info-api
kubectl wait --for=condition=available --timeout=300s deployment/orders-api  
kubectl wait --for=condition=available --timeout=300s deployment/profile-api

echo "✅ APIs deployed successfully!"
echo ""
echo "🔍 Check status:"
echo "   kubectl get pods"
echo "   kubectl get services"