
# Securing APIs with Amazon Cognito and API Gateway

## Overview

Amazon Cognito user pools act as a fully managed OAuth 2.0 and OpenID Connect (OIDC) authorization server. They issue JWT access tokens with scopes for fine-grained API authorization and standard claims like `sub` for unique user identification. When paired with API Gateway, you get a solid authorization layer in front of your APIs — but the built-in integration has limits. For anything beyond scope-based checks (matching `sub` to resource paths, restricting by user-agent, enforcing custom business rules), you'll need a Lambda authorizer that validates Cognito JWTs and generates IAM policies.

This guide walks through a practical implementation, including the gotchas and architectural decisions that aren't always obvious from the service docs alone.

---

## Step 1: Create and Configure the Cognito User Pool

Start by creating a user pool to handle authentication. You can do this through the console, CLI, SDK, or API — but the console is usually the fastest path for initial setup.

**Key configuration steps:**

- **App clients**: Create one for each application surface (web, mobile, backend). Enable the appropriate OAuth 2.0 flows — authorization code grant for server-side apps, implicit grant only if you have a strong reason (it's less secure and generally discouraged for new implementations).
- **Resource server**: Register a resource server to represent your protected APIs. Use a meaningful identifier like `https://yourapi.example.com`. This becomes the namespace for your custom scopes.
- **Custom scopes**: Define scopes that map to actual access patterns, not just CRUD operations. For example, `yourapi/read.user` for reading user data or `yourapi/write.user` for updates. Overly granular scopes become a maintenance burden — find the right balance for your use case.

**Common pitfall:** Forgetting to associate scopes with the app client after creating them on the resource server. If your token comes back without the scopes you expect, check the app client's "Allowed Custom Scopes" configuration first — this is the most frequent cause.

After this setup, Cognito issues JWTs on successful sign-in that include your custom scopes and standard claims like `sub`.

---

## Step 2: Understand and Use JWT Access Tokens

Users authenticate through the hosted UI, AWS Amplify, or SDKs (like the Amazon Cognito Identity SDK). On success, Cognito returns an access token (JWT) containing:

- **`scope`**: Space-separated list of granted scopes (e.g., `yourapi/read.user yourapi/write.user`) that define what the token holder can do.
- **`sub`**: A UUID uniquely identifying the user. This is your primary key for user-specific authorization downstream.
- **`cognito:groups`**: Group memberships, useful for role-based access patterns.

The access token goes in the `Authorization` header as a Bearer token when calling your APIs.

**Practical tips:**

- **Token validation**: Backend services (or authorizers) verify the JWT signature against the user pool's JWKS endpoint: `https://cognito-idp.{region}.amazonaws.com/{userPoolId}/.well-known/jwks.json`. Cache the JWKS keys — hitting this endpoint on every request adds unnecessary latency. Most JWT libraries handle this, but verify your library's caching behavior.
- **Pre Token Generation trigger**: You can use a Lambda trigger to add or modify claims before the token is issued. This is powerful but adds latency to every authentication. Use it sparingly and keep the function fast.
- **Token size**: Custom claims and group memberships increase token size. If your users belong to many groups, the token can exceed size limits for headers in some proxies and load balancers. Monitor this in production.

---

## Step 3: Integrate with API Gateway

API Gateway offers a built-in `COGNITO_USER_POOLS` authorizer that handles JWT validation with minimal setup:

1. Create an authorizer of type `COGNITO_USER_POOLS` in your API Gateway configuration.
2. Associate it with your user pool by providing the user pool ARN.
3. Set the token source to the `Authorization` header.
4. Enable the authorizer on your API methods (e.g., `GET /users/{userId}`).

The built-in authorizer validates the JWT signature, checks the issuer and audience, and enforces scopes. It's the right choice when scope-based authorization is all you need.

**Architectural trade-off:** The built-in authorizer is fast and simple, but it's a black box — you can't add custom logic. If you need to check `sub` against a path parameter, validate custom claims, or enforce any business rule beyond "does this token have the right scope," you'll need a Lambda authorizer instead. Decide this early; switching authorizer types later means updating every method in your API.

**For EKS-hosted backends:** Route requests from API Gateway to your EKS endpoint via VPC Link or ALB integration. The backend receives the validated request with claims available in the request context — make sure your EKS ingress configuration preserves these headers.

---

## Step 4: Implement Fine-Grained Authorization

Scope-based authorization gets you method-level protection. For user-level protection (ensuring users access only their own data), you have two paths:

### Option A: Backend Enforcement (Simpler)

Pass the `sub` claim to your backend using `$context.authorizer.claims.sub` in the integration request mapping. Your API logic then filters resources accordingly (e.g., `WHERE user_id = :sub` in database queries).

This is the approach that works for most teams. It's straightforward, testable, and doesn't require managing IAM policies dynamically.

### Option B: Lambda Authorizer (Stricter)

For cases where you want to reject unauthorized requests before they hit your backend, use a Lambda authorizer that generates conditional IAM policies:

1. Create a `TOKEN`-type Lambda authorizer in API Gateway.
2. In the Lambda function:
   - Validate the Cognito JWT (verify signature against JWKS, check expiration and issuer).
   - Extract the `sub` claim.
   - Generate an IAM policy that conditionally allows access only when `sub` matches the requested resource.

Example policy structure:

```json
{
  "principalId": "user",
  "policyDocument": {
    "Version": "2012-10-17",
    "Statement": [
      {
        "Action": "execute-api:Invoke",
        "Effect": "Allow",
        "Resource": "arn:aws:execute-api:{region}:{account}:{apiId}/{stage}/{method}/{path}",
        "Condition": {
          "StringEquals": {
            "aws:request.path.userId": "${context.authorizer.sub}"
          }
        }
      }
    ]
  },
  "context": {
    "sub": "<sub from token>"
  }
}
```

**Lessons learned with Lambda authorizers:**

- **Cold starts matter.** The authorizer runs on every API call (unless cached). Keep dependencies minimal and consider provisioned concurrency if latency is critical.
- **Cache the policy.** API Gateway can cache authorizer responses by token. Set a reasonable TTL — too short and you pay for Lambda invocations; too long and revoked tokens stay valid.
- **Use a proven JWT validation library.** Don't roll your own signature verification. Libraries like `aws-jwt-verify` (Node.js) or `python-jose` handle the JWKS retrieval and caching correctly.

---

## Step 5: Restrict by User-Agent

Cognito doesn't handle user-agent restrictions — this is purely a request-header concern that belongs in your authorization layer. Implement it in a Lambda authorizer:

1. Access the request headers via `event.headers['User-Agent']`.
2. Check against your allow/deny list (e.g., block `curl`, `Postman`, or custom automation agents).
3. Return a `Deny` policy if the user-agent is disallowed.

**A word of caution:** User-agent strings are trivially spoofable. This is a speed bump, not a security boundary. It's useful for discouraging casual misuse of APIs, but don't rely on it as a primary security control. For stronger client validation, consider mutual TLS or API keys in combination with Cognito tokens.

---

## Step 6: Testing and Operational Considerations

**Testing workflow:**

1. Obtain a token from Cognito (via the hosted UI or programmatically through the SDK).
2. Call your API with the token in the `Authorization: Bearer <token>` header.
3. Verify that scope enforcement, `sub` matching, and user-agent restrictions all behave as expected.
4. Test with expired tokens, revoked tokens, and tokens from other user pools to confirm rejection.

**Operational best practices:**

- **Token revocation**: Enable token revocation in your user pool if you need the ability to invalidate tokens before expiry. Be aware that revocation only works with the built-in Cognito authorizer or if your Lambda authorizer checks the revocation endpoint — cached authorizer responses won't reflect revocations.
- **Refresh tokens**: Use refresh tokens for long-lived sessions instead of issuing long-expiry access tokens. Shorter access token lifetimes (15-60 minutes) limit the blast radius of a compromised token.
- **Monitoring**: Enable CloudWatch logging on both the API Gateway authorizer and the Lambda function. Authorizer failures are often silent from the client's perspective (they just see a 403), so server-side logs are essential for debugging.
- **Consider Amazon Verified Permissions (AVP)**: For complex authorization models with relationships between entities (e.g., "user X can access resource Y because they belong to organization Z"), AVP provides policy-based authorization that scales better than hand-rolled IAM policies in Lambda.

---

## Architecture Summary

| Layer | Component | Responsibility |
|-------|-----------|---------------|
| Authentication | Cognito User Pool | User sign-in, token issuance, MFA |
| Token Validation | API Gateway Authorizer | JWT signature verification, scope checks |
| Fine-Grained AuthZ | Lambda Authorizer / Backend Logic | `sub` matching, custom conditions, user-agent filtering |
| Policy-Based AuthZ | Amazon Verified Permissions (optional) | Complex relationship-based access control |

The key insight is that Cognito handles *authentication and token issuance*, API Gateway handles *scope-based authorization*, and everything beyond that requires custom implementation — either in a Lambda authorizer or in your backend logic. Choosing where to draw that line depends on your security requirements and operational complexity tolerance.
