
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
  - **S3**: `CreateBucket`, `PutObject`, `PutBucketPublicAccessBlock`, `PutEncryptionConfiguration` (artifact bucket for the Lambda package)
- An active VPC with at least 2 availability zones

**Required Tools:**
- [AWS CLI v2](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html) configured with a default region
- [AWS CDK v2](https://docs.aws.amazon.com/cdk/v2/guide/getting-started.html) (`npm install -g aws-cdk`)
- [kubectl v1.24+](https://kubernetes.io/docs/tasks/tools/) installed and configured
- [Python 3.9+](https://www.python.org/downloads/) with `pip` (for demo scripts and building the Lambda package)
- [jq](https://jqlang.github.io/jq/) (used by `deploy.sh`)
- [Docker](https://docs.docker.com/get-docker/) (for container builds, if applicable)

## Key Concepts

If you're unfamiliar with any of the services used in this demo, here's a quick orientation:

- **[Amazon Cognito](https://docs.aws.amazon.com/cognito/latest/developerguide/what-is-amazon-cognito.html)** — Managed user authentication service. Think of it as the "login system" that issues JWT tokens after a user signs in.
- **[API Gateway](https://docs.aws.amazon.com/apigateway/latest/developerguide/welcome.html)** — Managed service that sits in front of your APIs, handling routing, throttling, and authorization.
- **[Lambda Authorizer](https://docs.aws.amazon.com/apigateway/latest/developerguide/apigateway-use-lambda-authorizer.html)** — A Lambda function that API Gateway calls before forwarding a request. It inspects the JWT token and decides Allow or Deny.
- **[Amazon EKS](https://docs.aws.amazon.com/eks/latest/userguide/what-is-eks.html)** — Managed Kubernetes service. Used here as an optional backend — the authorization pattern works with any backend.
- **JWT `sub` claim** — The `sub` (subject) field in a JSON Web Token is a unique identifier for the authenticated user. [Learn more about JWTs](https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-using-tokens-verifying-a-jwt.html).

## How It Works

When a user calls `GET /users/{userId}/orders`, the Lambda authorizer ([`lambda/authorizer/app.py`](lambda/authorizer/app.py)):

1. Extracts the `Bearer` token from the `Authorization` header
2. Verifies the JWT signature with [PyJWT](https://pyjwt.readthedocs.io/) against the [Cognito JWKS endpoint](https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-using-tokens-verifying-a-jwt.html), accepting `RS256` only
3. Checks `exp`, `iss` (this user pool), `token_use` (`access`), and `client_id` (this app client)
4. Returns an `Allow` policy scoped to the caller's own resources: `/users/{sub}` and `/users/{sub}/*`

No claim is trusted until the signature is verified. A token with a missing, altered, or fake signature is rejected with `401 Unauthorized`.

Here's the core of the Lambda function:

```python
# From lambda/authorizer/app.py — this is the real code, not pseudocode

_jwks_client = PyJWKClient(JWKS_URL, cache_keys=True, lifespan=3600, timeout=5)

def verify_access_token(token):
    # Look up the public key by the token's `kid`, then verify the signature,
    # expiry, and issuer before reading any claim.
    signing_key = _jwks_client.get_signing_key_from_jwt(token)
    claims = jwt.decode(
        token,
        signing_key.key,
        algorithms=['RS256'],
        issuer=ISSUER,
        options={'require': ['exp', 'iat', 'iss', 'sub', 'token_use', 'client_id']},
    )
    if claims['token_use'] != 'access':
        raise ValueError('Token is not an access token')
    if claims['client_id'] != APP_CLIENT_ID:
        raise ValueError('Token was not issued for this app client')
    ...
    return claims

def user_resource_arns(method_arn, sub):
    # methodArn: arn:aws:execute-api:{region}:{account}:{apiId}/{stage}/{verb}/{resource...}
    api_stage_arn = '/'.join(method_arn.split('/')[:2])
    return [
        '{}/GET/users/{}'.format(api_stage_arn, sub),
        '{}/GET/users/{}/*'.format(api_stage_arn, sub),
    ]
```

The policy covers the caller's own paths rather than only the requested one. API Gateway caches the authorizer result per token (300 seconds here), so the cached policy has to give the right answer for every path that token is later used on.

**What happens on mismatch:**

```
GET /users/other-user-id/orders
Authorization: Bearer <valid token with sub=my-user-id>

→ The authorizer's policy only allows /users/my-user-id and /users/my-user-id/*
→ API Gateway returns 403 Forbidden
→ Request never reaches backend
```

**What happens with a forged or invalid token:**

```
GET /users/victim-user-id/orders
Authorization: Bearer <token with sub=victim-user-id and a fake signature>

→ Signature verification fails
→ API Gateway returns 401 Unauthorized
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

The script builds the Lambda authorizer package (installing PyJWT and `cryptography` wheels for the Lambda runtime), uploads it to a private S3 artifact bucket (`cognito-demo-artifacts-<account>-<region>`, or set `ARTIFACT_BUCKET` to use your own), and deploys the stack.

**Option B — Deploy manually with the AWS CLI:**

```bash
# Build the authorizer package for the Lambda runtime (Python 3.12, x86_64)
mkdir -p build/authorizer
python3 -m pip install -r lambda/authorizer/requirements.txt -t build/authorizer \
    --platform manylinux2014_x86_64 --implementation cp --python-version 3.12 --only-binary=:all:
cp lambda/authorizer/app.py build/authorizer/

# Upload the package and deploy (use an existing private bucket you own)
aws cloudformation package \
    --template-file cloudformation/infrastructure.yaml \
    --s3-bucket <YOUR_ARTIFACT_BUCKET> \
    --output-template-file build/packaged.yaml

aws cloudformation deploy \
    --template-file build/packaged.yaml \
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
3. Test that a user can access their own data (expect `200 OK`)
4. Test that a user is blocked from accessing another user's data (expect `403 Forbidden`)
5. Test that a request with no token is rejected (expect `401 Unauthorized`)
6. Test that a forged token (real claims, fake signature) is rejected (expect `401 Unauthorized`)

The script exits non-zero if any check fails.

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
Test 1: User1 accessing their own data (Expected: 200)
✓ PASS: 200 for info for user a1b2c3d4...
Test 2: User1 trying to access User2's data (Expected: 403)
✓ PASS: 403 for info for user e5f6g7h8...
Test 3: No Authorization header (Expected: 401)
✓ PASS: 401 for info for user a1b2c3d4...
Test 4: Forged token with fake signature (Expected: 401)
✓ PASS: 401 for info for user forged-a...

...

12/12 checks passed
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

