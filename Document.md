Amazon Cognito user pools serve as an authorization server for OAuth 2.0 and OpenID Connect (OIDC), issuing JWT access tokens that include scopes for fine-grained API authorization and standard claims like `sub` for unique user identification. When integrated with API Gateway, Cognito enables protection of APIs by validating tokens and enforcing scopes. For custom conditions (e.g., matching `sub` to resource paths or restricting user-agents), documentation recommends using a Lambda authorizer to validate Cognito JWTs and generate IAM policies, as the built-in COGNITO_USER_POOLS authorizer primarily handles scope-based authorization without deep custom logic.
This design focuses on Cognito's role in authentication and token issuance, with API Gateway handling authorization. User-specific access (e.g., via `sub`) can be enforced either in the backend API logic or via conditional policies in a Lambda authorizer. User-agent restrictions require custom implementation in Lambda, as they are not natively supported in Cognito.
### Step-by-Step Implementation Based on Official Documentation
#### Step 1: Create and Configure a Cognito User Pool
From the official documentation on integrating Cognito with API Gateway (referenced in Cognito user pool guides), start by creating a user pool to manage user authentication:
Use the Amazon Cognito console, AWS CLI, SDK, or API to create a user pool.
Configure app clients within the user pool for your application (e.g., web or mobile apps). Enable OAuth 2.0 flows like authorization code grant or implicit grant.
Define a resource server in the user pool to represent your protected APIs. This is outlined in the Cognito documentation on resource servers and custom scopes:
Navigate to the user pool in the console and add a resource server with an identifier (e.g., `https://yourapi.example.com`).
Create custom scopes for each protected API or resource, such as `yourapi.read/user` for reading user data or `yourapi.write/user` for updates. Scopes are namespaced and authorize specific access levels.
Ensure the user pool issues access tokens containing these scopes and standard claims like `sub` (a unique user identifier).
This setup allows Cognito to act as an OAuth 2.0 authorization server, issuing JWTs after user sign-in.
#### Step 2: Issue and Use JWT Access Tokens
As detailed in the Cognito documentation on understanding user pool JWTs and using access tokens:
Users authenticate via the user pool (e.g., using the hosted UI, AWS Amplify, or SDKs like Amazon Cognito Identity SDK).
Upon successful sign-in, Cognito returns an access token (JWT) that includes:
The `scope` claim: A space-separated list of granted scopes (e.g., `yourapi.read/user yourapi.write/user`), which define permissions for protected resources.
The `sub` claim: A unique identifier for the user (e.g., a UUID), used to associate the token with a specific user.
Other claims like `cognito:groups` for group-based access.
The access token is used in the `Authorization` header (Bearer token) when calling APIs.
Tokens can be customized via a Pre Token Generation Lambda trigger to add or modify claims, but standard claims like `sub` are always included for user-specific authorization.
For token validation, backend services (or authorizers) verify the JWT signature using the user pool's JWKS endpoint (`https://cognito-idp.{region}.amazonaws.com/{userPoolId}/.well-known/jwks.json`).
#### Step 3: Integrate with API Gateway for Authorization
Cognito documentation on accessing resources with API Gateway after sign-in recommends using Cognito as the authorizer for API protection:
In API Gateway, create an authorizer of type `COGNITO_USER_POOLS` (built-in JWT authorizer).
Associate it with your Cognito user pool by providing the user pool ARN.
Specify the token source as the `Authorization` header.
Enable the authorizer on API methods (e.g., GET /users/{userId}).
The built-in authorizer validates the JWT, checks the issuer, audience, and scopes. It authorizes based on scopes in the access token but does not natively support custom conditions like `sub` matching or user-agent restrictions.
For APIs hosted on EKS, route requests from API Gateway to the EKS endpoint (e.g., via VPC Link or ALB integration), ensuring the backend receives validated requests.
#### Step 4: Implement Fine-Grained Authorization with Scopes and Sub Claim
Per the documentation on access tokens and JWT claims:
Use scopes for API-level protection: The access token's `scope` claim must include the required scope for the API method (e.g., `yourapi.read/user` for user data access).
For user-specific restrictions (e.g., ensuring a user accesses only their own data):
Extract the `sub` claim from the validated token. This claim uniquely identifies the user and can be used in backend logic to filter resources (e.g., in database queries: `WHERE user_id = sub`).
In API Gateway, pass claims like `sub` to the backend via the integration request (e.g., using `$context.authorizer.claims.sub`).
If scope-based authorization is insufficient, Cognito documentation references using a Lambda authorizer for custom logic:
Create a TOKEN-type Lambda authorizer in API Gateway.
In the Lambda function, validate the Cognito JWT, check scopes, and generate an IAM policy document.
The policy can include conditions, such as matching `sub` to path parameters (e.g., userId in /users/{userId}).
Example policy structure from referenced authorization guides:
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
This allows denying access if `sub` does not match the requested userId.
#### Step 5: Restrict User-Agent (Custom Implementation)
Cognito documentation does not directly address user-agent restrictions, as they are header-based and require custom validation. For this, use a Lambda authorizer (as referenced in integration guides):
In the Lambda function, access the request headers (e.g., `event.headers['User-Agent']`).
Check against allowed patterns (e.g., browser user-agents like Mozilla/Chrome) and deny if it matches disallowed clients (e.g., curl or Postman).
If invalid, return a policy with `"Effect": "Deny"`.
This is implemented in the authorizer logic, not natively in Cognito.
#### Step 6: Testing and Best Practices
Test by obtaining a token from Cognito and invoking the API with the `Authorization` header.
Enable token revocation if needed, as mentioned in JWT guides.
Securely store tokens and use refresh tokens for long-lived sessions.
For enhanced security, combine with Amazon Verified Permissions (AVP) for policy-based authorization, as noted in Cognito docs.
This regeneration is derived solely from Amazon Cognito official documentation, including guides on user pools, resource servers, scopes, JWT claims, access tokens, and integrations with API Gateway (with references to Lambda for custom needs). For full details, refer to the AWS Documentation links provided in the sources.