#!/bin/bash

# Cleanup the Cognito Authorization Demo

set -e

echo "🧹 Cleaning up Cognito Authorization Demo..."

STACK_NAME="cognito-demo-authorizer-v2"

stack_output() {
    aws cloudformation describe-stacks --stack-name "$STACK_NAME" \
        --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text 2>/dev/null || true
}

# Delete security groups in the demo VPC that this stack did not create.
# Services outside the stack (for example AWS Firewall Manager security group
# policies in an AWS Organization) can add security groups to new VPCs, which
# blocks CloudFormation from deleting the VPC.
delete_unmanaged_security_groups() {
    local vpc_id="$1"
    if [ -z "$vpc_id" ] || [ "$vpc_id" = "None" ]; then
        return 0
    fi
    for sg in $(aws ec2 describe-security-groups --filters "Name=vpc-id,Values=${vpc_id}" \
            --query "SecurityGroups[?GroupName!='default' && !(Tags[?Key=='aws:cloudformation:stack-name'])].GroupId" \
            --output text 2>/dev/null); do
        echo "🗑️  Deleting security group ${sg} (not managed by the stack) in ${vpc_id}"
        aws ec2 delete-security-group --group-id "$sg" || true
    done
}

# Clean up K8s deployments if they exist
if kubectl get deployments > /dev/null 2>&1; then
    echo "🗑️  Deleting K8s deployments..."
    kubectl delete -f k8s/apis.yaml --ignore-not-found=true
fi

# Check if stack exists
if aws cloudformation describe-stacks --stack-name "$STACK_NAME" > /dev/null 2>&1; then
    VPC_ID=$(stack_output VpcId)
    APIGW_LOG_ROLE_ARN=$(stack_output ApiGatewayCloudWatchRoleArn)
    API_ID=$(stack_output ApiGatewayUrl | sed -E 's#https://([^.]+)\..*#\1#')

    echo "📦 Deleting CloudFormation stack: ${STACK_NAME}"
    aws cloudformation delete-stack --stack-name "$STACK_NAME"

    echo "⏳ Waiting for stack deletion to complete..."
    if ! aws cloudformation wait stack-delete-complete --stack-name "$STACK_NAME"; then
        echo "⚠️  Stack deletion failed; removing security groups added outside the stack and retrying..."
        delete_unmanaged_security_groups "$VPC_ID"
        aws cloudformation delete-stack --stack-name "$STACK_NAME"
        aws cloudformation wait stack-delete-complete --stack-name "$STACK_NAME"
    fi

    echo "✅ Stack deleted successfully!"

    # The stack set the account-level API Gateway CloudWatch Logs role. Deleting
    # the stack removes the role but not the setting, so clear it if it still
    # points at the deleted role.
    if [ -n "$APIGW_LOG_ROLE_ARN" ] && [ "$APIGW_LOG_ROLE_ARN" != "None" ]; then
        CURRENT_ROLE=$(aws apigateway get-account --query cloudwatchRoleArn --output text 2>/dev/null || true)
        if [ "$CURRENT_ROLE" = "$APIGW_LOG_ROLE_ARN" ]; then
            echo "🔧 Clearing API Gateway account CloudWatch Logs role setting"
            aws apigateway update-account \
                --patch-operations op=replace,path=/cloudwatchRoleArn,value='' > /dev/null
        fi
    fi

    # Lambda, EKS, and API Gateway execution logging create these log groups at
    # runtime, so they are not part of the stack and survive its deletion.
    LOG_GROUPS="/aws/lambda/cognito-demo-authorizer /aws/eks/cognito-demo-cluster/cluster"
    if [ -n "$API_ID" ] && [ "$API_ID" != "None" ]; then
        LOG_GROUPS="$LOG_GROUPS API-Gateway-Execution-Logs_${API_ID}/prod"
    fi
    for lg in $LOG_GROUPS; do
        if aws logs delete-log-group --log-group-name "$lg" > /dev/null 2>&1; then
            echo "🗑️  Deleted log group: ${lg}"
        fi
    done
else
    echo "ℹ️  Stack ${STACK_NAME} not found or already deleted"
fi

# Delete the artifact bucket that deploy.sh created for the Lambda package.
# A bucket you supplied via ARTIFACT_BUCKET is left alone.
if [ -z "${ARTIFACT_BUCKET:-}" ]; then
    ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
    REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-$(aws configure get region || true)}}"
    DEFAULT_BUCKET="cognito-demo-artifacts-${ACCOUNT_ID}-${REGION}"
    if aws s3api head-bucket --bucket "$DEFAULT_BUCKET" > /dev/null 2>&1; then
        echo "🗑️  Deleting artifact bucket: ${DEFAULT_BUCKET}"
        aws s3 rb "s3://${DEFAULT_BUCKET}" --force
    fi
else
    echo "ℹ️  Leaving your artifact bucket ${ARTIFACT_BUCKET} in place"
fi

rm -rf "$(dirname "$0")/build"

echo "🎉 Cleanup completed!"
