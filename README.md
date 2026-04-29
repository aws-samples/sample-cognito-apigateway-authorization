
# Cognito Authorization Demo

> **DISCLAIMER:** This code is provided as a sample for educational and testing
> purposes only. Users must perform their own security review and due diligence
> before deploying any code to production environments. The code provided
> represents a baseline implementation and may not address all security
> considerations for your specific environment.
>
> As our customer, any applications you integrate these examples into should be
> thoroughly tested, secured, and optimized according to your business's security
> standards and policies before deploying to production workloads.

> **Skill Level: Intermediate** — This demo requires familiarity with AWS services (IAM, CloudFormation), command-line usage, REST APIs, and JWT tokens. If you are building this knowledge, we recommend starting with the [AWS Cloud Practitioner Essentials](https://aws.amazon.com/training/digital/aws-cloud-practitioner-essentials/) course, then returning to this demo.

Demonstrates user-specific data protection using Amazon Cognito, API Gateway, and a Lambda authorizer. The core security rule: **users can only access their own data.** Any request where the URL's `userId` doesn't match the caller's JWT `sub` claim gets denied at the API Gateway layer — before it ever reaches your backend.

## Prerequisites

Before deploying this sample, ensure you have the following:

**AWS Account & Permissions:**
- An active AWS account with IAM permissions for:
  - **Amazon Cognito**: `CreateUserPool`, `AdminCreateUser`, `DescribeUserPool`
  - **API Gateway**: `CreateRestApi`, `CreateDeployment`, `CreateAuthorizer`
  - **Lambda**: `CreateFunction`, `AddPermission`, `UpdateFunctionCode`
  - **EKS**: `CreateCluster`, `DescribeCluster`, `UpdateKubeconfig`
  - **IAM**: `CreateRole`, `AttachRolePolicy`, `CreatePolicy`
  - **KMS**: `CreateKey`, `CreateAlias`, `Encrypt`, `Decrypt`
  - **CloudFormation**: `CreateStack`, `DescribeStacks`, `DeleteStack`
  - **VPC/EC2**: `CreateVpc`, `CreateSubnet`, `CreateSecurityGroup`
- An active VPC with at least 2 availability zones

**Required Tools:**
- [AWS CLI v2](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html) configured with a default region
- [AWS CDK v2](https://docs.aws.amazon.com/cdk/v2/guide/getting-started.html) (`npm install -g aws-cdk`)
- [kubectl v1.24+](https://kubernetes.io/docs/tasks/tools/) installed and configured
- [Python 3.9+](https://www.python.org/downloads/) (for demo scripts)
- [Docker](https://docs.docker.com/get-docker/) (for container builds, if applicable)

## Key Concepts

If you're unfamiliar with any of the services used in this demo, here's a quick orientation:

- **[Amazon Cognito](https://docs.aws.amazon.com/cognito/latest/developerguide/what-is-amazon-cognito.html)** — Managed user authentication service. Think of it as the "login system" that issues JWT tokens after a user signs in.
- **[API Gateway](https://docs.aws.amazon.com/apigateway/latest/developerguide/welcome.html)** — Managed service that sits in front of your APIs, handling routing, throttling, and authorization.
- **[Lambda Authorizer](https://docs.aws.amazon.com/apigateway/latest/developerguide/apigateway-use-lambda-authorizer.html)** — A Lambda function that API Gateway calls before forwarding a request. It inspects the JWT token and decides Allow or Deny.
- **[Amazon EKS](https://docs.aws.amazon.com/eks/latest/userguide/what-is-eks.html)** — Managed Kubernetes service. Used here as an optional backend — the authorization pattern works with any backend.
- **JWT `sub` claim** — The `sub` (subject) field in a JSON Web Token is a unique identifier for the authenticated user. [Learn more about JWTs](https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-using-tokens-verifying-a-jwt.html).

## How It Works

When a user calls `GET /users/{userId}/orders`, the Lambda authorizer:

1. Extracts the `Bearer` token from the `Authorization` header
2. Validates the JWT against the [Cognito JWKS endpoint](https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-using-tokens-verifying-a-jwt.html)
3. Compares the token's `sub` claim (the user's unique ID) to the `{userId}` in the request path
4. Returns `Allow` if they match, `Deny` if they don't

Here's the actual enforcement logic from the Lambda function:

```python
# From the Lambda authorizer — this is the real code, not pseudocode

# Extract the userId from the API Gateway method ARN
# ARN format: arn:aws:execute-api:{region}:{account}:{api}/{stage}/{method}/users/{userId}/...
arn_parts = method_arn.split('/')
resource_path = '/'.join(arn_parts[3:])
path_segments = resource_path.split('/')
user_idx = path_segments.index('users')
user_id_from_path = path_segments[user_idx + 1]

# Decode the JWT and extract the sub claim
payload = decode_jwt_payload(token)  # base64-decodes the JWT payload
sub = payload.get('sub', '')

# Deny if the path userId doesn't match the token's sub
if user_id_from_path != sub:
    return generate_policy(sub, 'Deny', method_arn)

return generate_policy(sub, 'Allow', method_arn)

```

**What happens on mismatch:**

```
GET /users/other-user-id/orders
Authorization: Bearer <token with sub=my-user-id>

→ Lambda authorizer returns Deny
→ API Gateway returns 403 Forbidden
→ Request never reaches backend
```

## Architecture

```
┌──────────┐     ┌───────────────┐     ┌──────────────────┐     ┌─────────────┐
│  Client   │────▶│  API Gateway  │────▶│ Lambda Authorizer│     │  EKS / Mock │
│ (Browser/ │     │  (Regional)   │     │  (JWT Validation │     │  Backend    │
│  SDK)     │◀────│               │◀────│   + sub Match)   │────▶│             │
└──────────┘     └───────────────┘     └──────────────────┘     └─────────────┘
                                              │
                                              ▼
                                       ┌──────────────┐
                                       │ Cognito User │
                                       │ Pool (JWKS)  │
                                       └──────────────┘
```

**What gets deployed:**

| Resource | Purpose |
|----------|---------|
| VPC with public/private subnets | Network isolation across 2 AZs |
| NAT Gateway | Outbound internet for private subnets |
| Cognito User Pool + App Client | User authentication and JWT issuance |
| Lambda Authorizer | JWT validation and `sub` claim enforcement |
| API Gateway (Regional) | REST API with 3 protected endpoints |
| EKS Cluster + Node Group | Optional Kubernetes backend |
| KMS Key | Encryption for EKS secrets, Lambda env vars, CloudWatch Logs |
| VPC Flow Logs | Network traffic audit logging |

## Deployment

### Step 1: Clone the Repository

```bash
git clone https://github.com/aws-samples/sample-cognito-apigateway-authorization.git
cd sample-cognito-apigateway-authorization
```

### Step 2: Verify Prerequisites

Make sure your AWS CLI is configured and has the required permissions:

```bash
aws sts get-caller-identity
```

You should see your account ID and IAM principal. If this fails, run `aws configure` first.

### Step 3: Deploy the Infrastructure

**Option A — Use the deploy script (recommended):**

```bash
chmod +x deploy.sh
./deploy.sh
```

**Option B — Deploy manually with the AWS CLI:**

```bash
aws cloudformation deploy \
    --template-file cloudformation/infrastructure.yaml \
    --stack-name cognito-demo-authorizer-v2 \
    --capabilities CAPABILITY_IAM \
    --parameter-overrides EnvironmentName=cognito-demo
```

Deployment takes approximately 15–20 minutes (EKS cluster creation is the bottleneck).

### Step 4: Note the Stack Outputs

After deployment completes, retrieve the outputs you'll need for testing:

```bash
aws cloudformation describe-stacks \
    --stack-name cognito-demo-authorizer-v2 \
    --query 'Stacks[0].Outputs' \
    --output table
```

You'll see:

| Output | Description |
|--------|-------------|
| `UserPoolId` | Cognito User Pool ID for authentication |
| `UserPoolClientId` | App client ID for token requests |
| `ApiGatewayUrl` | Base URL for the protected API (e.g., `https://{id}.execute-api.{region}.amazonaws.com/prod`) |
| `EKSClusterName` | EKS cluster name (if deploying K8s workloads) |

### Step 5: (Optional) Deploy APIs to EKS

If you want to run the backend APIs on EKS instead of using MOCK integrations:

```bash
chmod +x deploy-eks-apis.sh
./deploy-eks-apis.sh
```

This updates your kubeconfig and deploys three hardened Kubernetes deployments (user-info, orders, profile) into a dedicated `cognito-demo` namespace.

Verify the pods are running:

```bash
kubectl get pods -n cognito-demo
```

### Step 6: Run the Demo Test

Install Python dependencies and run the automated test:

```bash
pip install -r requirements.txt
python3 demo-scripts/test-demo.py
```

The test script will:
1. Create two test users (`testuser1`, `testuser2`) in the Cognito User Pool
2. Authenticate both users and obtain JWT access tokens
3. Test that each user can access their own data (expect `200 OK`)
4. Test that each user is blocked from accessing the other's data (expect `403 Forbidden`)

**Expected output:**

```
Starting User-Specific Data Protection Demo

Step 1: Creating test users...
✓ Created user: testuser1
✓ Created user: testuser2

Step 2: Getting access tokens...
✓ Got token for testuser1 (sub: a1b2c3d4...)
✓ Got token for testuser2 (sub: e5f6g7h8...)

Step 3: Testing API access scenarios...

--- Testing User Info API (GET /users/{userId}) ---
Test 1: User1 accessing their own data (Expected: ALLOW)
✓ SUCCESS: Access granted to info for user a1b2c3d4...
Test 2: User1 trying to access User2's data (Expected: DENY)
✓ SUCCESS: Access denied to info for user e5f6g7h8... (as expected)

...

Demo completed successfully!
```

### Step 7: Test Manually with curl

You can also test the API directly. First, get a token for a test user:

```bash
# Authenticate and get an access token
TOKEN=$(aws cognito-idp admin-initiate-auth \
    --user-pool-id <YOUR_USER_POOL_ID> \
    --client-id <YOUR_CLIENT_ID> \
    --auth-flow ADMIN_NO_SRP_AUTH \
    --auth-parameters USERNAME=testuser1,PASSWORD=TempPass123! \
    --query 'AuthenticationResult.AccessToken' \
    --output text)
```

Then call the API — replace `<USER_SUB>` with the `sub` claim from the token:

```bash
# Access your own data (should return 200)
curl -H "Authorization: Bearer $TOKEN" \
    <YOUR_API_URL>/users/<USER_SUB>/orders

# Try accessing another user's data (should return 403)
curl -H "Authorization: Bearer $TOKEN" \
    <YOUR_API_URL>/users/some-other-user-id/orders
```

## Cleanup

Remove all deployed resources:

```bash
chmod +x cleanup.sh
./cleanup.sh
```

This deletes the Kubernetes deployments (if any) and the CloudFormation stack, including the Cognito User Pool, Lambda function, API Gateway, EKS cluster, VPC, and all associated resources.

To verify cleanup is complete:

```bash
aws cloudformation describe-stacks --stack-name cognito-demo-authorizer-v2
# Should return "Stack does not exist"
```

## Security Considerations

> **This reference implementation is NOT production-ready without additional security review.** The patterns demonstrated here are a starting point — adapt them to your organization's security requirements before deploying to production.

### Authentication & Authorization

- **Token expiry**: Cognito User Pool tokens have configurable expiry. Set short-lived access tokens (1 hour or less) and rotate refresh tokens regularly.
- **Authorizer caching**: The Lambda Authorizer caches policy results (default 300s TTL). Tune the cache TTL based on your security requirements — shorter TTLs mean revoked tokens are rejected faster, but increase Lambda invocations.
- **Audience validation**: Scope JWT validation to specific Cognito User Pool ARNs. Avoid wildcard audience validation.

### IAM Least Privilege

- **Demo IAM policies**: This demo uses broad IAM policies for simplicity. Before production, replace wildcard (`*`) resources with specific ARNs for each API and function.
- **EKS pod identity**: Use [IAM Roles for Service Accounts (IRSA)](https://docs.aws.amazon.com/eks/latest/userguide/iam-roles-for-service-accounts.html) for EKS pods rather than node-level instance profiles.

### Network Security

- **VPC Flow Logs**: This template enables VPC Flow Logs for audit logging and anomaly detection.
- **Security Groups**: Use Security Groups to restrict traffic between API Gateway, Lambda, and EKS namespaces.
- **WAF**: Consider [AWS WAF](https://docs.aws.amazon.com/waf/latest/developerguide/what-is-aws-waf.html) on API Gateway for additional protection against common web exploits.

### Production Hardening

- Conduct penetration testing per your organization's security policies before production deployment.
- Enable [CloudTrail](https://docs.aws.amazon.com/awscloudtrail/latest/userguide/cloudtrail-user-guide.html) and CloudWatch Logs for all API calls and Lambda invocations.
- Use [AWS Secrets Manager](https://docs.aws.amazon.com/secretsmanager/latest/userguide/intro.html) for any secrets rather than environment variables.
- Implement rate limiting and throttling appropriate for your traffic patterns.
- Review and harden Kubernetes manifests per your organization's pod security standards.

## License

This project is licensed under the MIT-0 License. See the [LICENSE](LICENSE) file for details.

