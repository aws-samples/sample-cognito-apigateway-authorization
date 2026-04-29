# Cognito Authorization Demo

Demonstrates user-specific data protection using Amazon Cognito, API Gateway, and a Lambda authorizer. The core security rule: **users can only access their own data.** Any request where the URL's `userId` doesn't match the caller's JWT `sub` claim gets denied at the API Gateway layer — before it ever reaches your backend.

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

```
                    ┌──────────┐     ┌─────────────┐     ┌───────────────────┐     ┌───────────┐
  User request ---->│ Cognito  │---->│ API Gateway │---->│ Lambda Authorizer │---->│ Backend   │
  (with JWT)        │ (issued  │     │ (routes     │     │ (validates JWT,   │     │ (EKS or   │
                    │  token)  │     │  request)   │     │  enforces sub ==  │     │  mock)    │
                    └──────────┘     └─────────────┘     │  userId match)    │     └───────────┘
                                                         └───────────────────┘
                                                           │ DENY if mismatch
                                                           └──> 403 Forbidden
```

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/users/{userId}` | User information |
| `GET` | `/users/{userId}/orders` | User orders |
| `GET` | `/users/{userId}/profile` | User profile settings |

All three endpoints enforce the same `sub == userId` authorization check.

## Prerequisites

- **AWS CLI v2** — [install guide](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html), configured with credentials
- **Python 3.10+** — for the demo test script
- **kubectl** — [install guide](https://docs.aws.amazon.com/eks/latest/userguide/install-kubectl.html) (only if deploying the EKS backend)

**IAM permissions for deployment:** Your CLI profile needs permissions to create these resources:

```
cognito-idp:CreateUserPool, cognito-idp:CreateUserPoolClient
cognito-idp:AdminCreateUser, cognito-idp:AdminSetUserPassword, cognito-idp:AdminInitiateAuth
apigateway:* (scoped to the demo API)
lambda:CreateFunction, lambda:AddPermission, lambda:GetFunction
iam:CreateRole, iam:PutRolePolicy, iam:PassRole
cloudformation:CreateStack, cloudformation:DescribeStacks, cloudformation:DeleteStack
eks:CreateCluster, eks:CreateNodegroup (only if using EKS backend)
s3:GetObject (for CloudFormation template storage)
```

> In production, scope these down further. See the CloudFormation template in `cloudformation/infrastructure.yaml` for the exact resources being created.

## Quick Start

```bash
# 1. Clone the repo
git clone <repository-url>
cd cognito-apigateway-authorization

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. Deploy infrastructure (Cognito, API Gateway, Lambda, IAM)
chmod +x deploy.sh cleanup.sh
./deploy.sh

# 4. (Optional) Deploy sample APIs to EKS
chmod +x deploy-eks-apis.sh
./deploy-eks-apis.sh

# 5. Run the demo
python3 demo-scripts/test-demo.py
```

After `deploy.sh` completes, you'll see output like:

```
Stack creation complete.
User Pool ID:  YOUR_USER_POOL_ID
Client ID:     YOUR_CLIENT_ID
API URL:       https://abc123def4.execute-api.us-east-1.amazonaws.com/dev
```

Save these values — you'll need them for manual testing.

## Demo Scenarios

The test script creates two users and runs three scenarios that demonstrate the authorization boundary:

| Scenario | Request | Expected Result | Why |
|---|---|---|---|
| User1 reads own orders | `GET /users/{user1-sub}/orders` with User1's token | **200 OK** | `sub` matches `userId` in path |
| User1 reads User2's orders | `GET /users/{user2-sub}/orders` with User1's token | **403 Denied** | `sub` ≠ `userId` — Lambda returns Deny policy |
| User2 reads own profile | `GET /users/{user2-sub}/profile` with User2's token | **200 OK** | `sub` matches `userId` in path |

The key takeaway: **the token determines identity, the URL determines the resource, and the Lambda authorizer ensures they align.** This prevents horizontal privilege escalation — even if User1 knows User2's ID, they can't access User2's data.

## Manual Testing

You can test the authorization flow directly with `curl`.

**Step 1: Get an access token**

```bash
# Replace with your actual User Pool ID and Client ID from deploy.sh output
USER_POOL_ID="<your-user-pool-id>"
CLIENT_ID="<your-client-id>"

TOKEN=$(aws cognito-idp admin-initiate-auth \
  --user-pool-id "$USER_POOL_ID" \
  --client-id "$CLIENT_ID" \
  --auth-flow ADMIN_NO_SRP_AUTH \
  --auth-parameters USERNAME=testuser1,PASSWORD="<[PASSWORD]>" \
  --query 'AuthenticationResult.AccessToken' \
  --output text)

echo "$TOKEN"
```

> **Note on `ADMIN_NO_SRP_AUTH`:** This auth flow bypasses [Secure Remote Password protocol](https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-authentication-flow.html) and is intended for trusted server-side use only. In production client apps, use `USER_SRP_AUTH` or the [hosted UI](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-pools-app-integration.html) instead.

**Step 2: Test authorized access (should succeed)**

```bash
API_URL="<your-api-gateway-url>"
USER1_SUB="<user1-sub-from-token>"

curl -s -w "
HTTP Status: %{http_code}
" \
  -H "Authorization: Bearer $TOKEN" \
  "$API_URL/users/$USER1_SUB/orders"
```

**Step 3: Test cross-user access (should fail with 403)**

```bash
USER2_SUB="<user2-sub>"

curl -s -w "
HTTP Status: %{http_code}
" \
  -H "Authorization: Bearer $TOKEN" \
  "$API_URL/users/$USER2_SUB/orders"
# Expected: 403 Forbidden — User1's token can't access User2's data
```

## Project Structure

```
cognito-apigateway-authorization/
├── README.md                        # This guide
├── deploy.sh                        # Deploys CloudFormation stack
├── deploy-eks-apis.sh               # Deploys sample APIs to EKS (optional)
├── cleanup.sh                       # Tears down all resources
├── requirements.txt                 # Python dependencies (boto3, requests)
├── cloudformation/
│   └── infrastructure.yaml          # Cognito, API GW, Lambda, EKS, IAM
├── demo-scripts/
│   └── test-demo.py                 # Automated 3-scenario test
└── k8s/
    └── apis.yaml                    # Kubernetes service definitions
```

### With vs. Without EKS

The EKS deployment (`deploy-eks-apis.sh`) is optional. Here's what changes:

| Component | Without EKS | With EKS |
|---|---|---|
| API Gateway integration | Mock responses (returns sample JSON) | Routes to EKS services via VPC Link |
| Authorization check | Same — Lambda authorizer handles it | Same — Lambda authorizer handles it |
| Backend data | Static mock data | Dynamic responses from K8s pods |

The authorization pattern is identical either way — the Lambda authorizer sits in front of API Gateway regardless of backend. Skip EKS if you're focused on learning the Cognito + Lambda authorizer pattern.

## Security Considerations

### ⚠️ This Is a Demo — Not Production-Ready

This demo uses simplified security for clarity. Here's what to change for production:

**Authentication:**
- Replace `ADMIN_NO_SRP_AUTH` with `USER_SRP_AUTH` or OAuth 2.0 authorization code flow for client apps — [auth flows guide](https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-authentication-flow.html)
- Enable [MFA](https://docs.aws.amazon.com/cognito/latest/developerguide/user-pool-settings-mfa.html) on the Cognito user pool
- Set up [token revocation](https://docs.aws.amazon.com/cognito/latest/developerguide/token-revocation.html) to invalidate compromised tokens

**Authorization:**
- The demo uses mock integrations — real backends should also validate the `sub` claim server-side (defense in depth)
- Add [WAF rate limiting](https://docs.aws.amazon.com/waf/latest/developerguide/waf-rule-statement-type-rate-based.html) on API Gateway to prevent brute-force token testing
- Consider [Amazon Verified Permissions](https://docs.aws.amazon.com/verifiedpermissions/latest/userguide/what-is-avp.html) for complex policy logic beyond `sub` matching

**Infrastructure:**
- The CloudFormation template has known security findings (see `eks-scan-report.json` in this repo). Key remediations: add EKS encryption, move Lambda into VPC, upgrade runtime to Python 3.12.
- Use [VPC endpoints](https://docs.aws.amazon.com/vpc/latest/privatelink/what-is-privatelink.html) for private connectivity between API Gateway and backend services
- Enable [CloudTrail](https://docs.aws.amazon.com/awscloudtrail/latest/userguide/cloudtrail-user-guide.html) for audit logging of all API calls

## Troubleshooting

**`deploy.sh` fails with "Stack already exists"**

Delete the existing stack first: `aws cloudformation delete-stack --stack-name cognito-demo` and wait for deletion to complete before redeploying.

**403 on every request (even valid ones)**

Check that you're using the **access token**, not the ID token. `admin-initiate-auth` returns both — the access token is in `AuthenticationResult.AccessToken`.

**"Token expired" errors**

Cognito access tokens expire after 1 hour by default. Get a fresh token by re-running the `admin-initiate-auth` command.

**EKS nodes not joining the cluster**

Verify the node group's IAM role has `AmazonEKSWorkerNodePolicy`, `AmazonEKS_CNI_Policy`, and `AmazonEC2ContainerRegistryReadOnly`. Check node status with `kubectl get nodes`.

**Lambda authorizer caching stale results**

API Gateway caches authorizer responses for 300 seconds by default. During testing, you can set `AuthorizerResultTtlInSeconds: 0` in the CloudFormation template to disable caching.

## Cleanup

Remove all created resources:

```bash
./cleanup.sh
```

This deletes the CloudFormation stack including: EKS cluster and node group, Cognito user pool and users, API Gateway and stage, Lambda function and IAM roles, VPC and networking resources, and Kubernetes deployments (if EKS was deployed).

## References

- [Cognito User Pools Developer Guide](https://docs.aws.amazon.com/cognito/latest/developerguide/what-is-amazon-cognito.html) — user pool setup, token handling, and app integration
- [API Gateway Lambda Authorizers](https://docs.aws.amazon.com/apigateway/latest/developerguide/apigateway-use-lambda-authorizer.html) — TOKEN and REQUEST authorizer types, policy format, caching
- [JWT Token Verification](https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-using-tokens-verifying-a-jwt.html) — JWKS endpoint, signature validation, claim verification
- [EKS User Guide](https://docs.aws.amazon.com/eks/latest/userguide/what-is-eks.html) — cluster setup, node groups, and kubectl configuration
- [Amazon Verified Permissions](https://docs.aws.amazon.com/verifiedpermissions/latest/userguide/what-is-avp.html) — Cedar-based policy engine for complex authorization scenarios beyond this demo

---

*This demo is for educational purposes. In production, use MFA-enabled authentication, scoped IAM policies, VPC-isolated Lambda functions, and defense-in-depth authorization with server-side sub validation.*


## CSR F