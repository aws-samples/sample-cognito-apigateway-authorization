
# Cognito Authorization Demo

> **Skill Level: Intermediate** — This demo assumes working knowledge of AWS services (IAM, CloudFormation), basic command-line usage, and familiarity with REST APIs and JWT tokens. If you're new to AWS, start with the [AWS Cloud Practitioner Essentials](https://aws.amazon.com/training/digital/aws-cloud-practitioner-essentials/) course first.

Demonstrates user-specific data protection using Amazon Cognito, API Gateway, and a Lambda authorizer. The core security rule: **users can only access their own data.** Any request where the URL's `userId` doesn't match the caller's JWT `sub` claim gets denied at the API Gateway layer — before it ever reaches your backend.

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
