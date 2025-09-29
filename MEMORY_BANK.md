# Cognito Authorizer Demo - Memory Bank

## Project Overview
Demo project showcasing user-specific data protection using Amazon Cognito, API Gateway, and Lambda authorizer. Ensures users can only access their own data through fine-grained authorization.

## Core Requirements
- **Primary Goal**: Prevent users from accessing other users' data
- **Example**: getUserInfo should only return the requester's own details
- **Technology Stack**: CloudFormation, Cognito User Pools, API Gateway, Lambda Authorizer
- **Authorization Method**: JWT token validation with `sub` claim matching

## Architecture Components

### 1. Amazon Cognito User Pool
- **Purpose**: Authentication and JWT token issuance
- **Configuration**: 
  - Password policy with complexity requirements
  - Email as required attribute
  - Client with USER_PASSWORD_AUTH flow
- **Token Claims**: Contains `sub` (unique user identifier) for authorization

### 2. Lambda Authorizer Function
- **Runtime**: Python 3.9
- **Key Logic**:
  - Validates JWT signature using Cognito JWKS endpoint
  - Extracts `sub` claim from token
  - Extracts `userId` from API path
  - **Critical Check**: Denies access if `sub` ≠ `userId` in path
  - Additional: Blocks curl/Postman user agents for demo
- **Returns**: IAM policy (Allow/Deny) with user context

### 3. API Gateway
- **Authorizer Type**: TOKEN (Lambda-based)
- **Protected Endpoints**:
  - `GET /users/{userId}` - User info
  - `GET /users/{userId}/orders` - User orders  
  - `GET /users/{userId}/profile` - User profile
- **Integration**: MOCK responses with user context injection

## Security Model

### Authorization Flow
1. User authenticates with Cognito → receives JWT with `sub` claim
2. API request includes JWT in Authorization header
3. Lambda authorizer validates JWT and extracts `sub`
4. Authorizer compares `sub` with `{userId}` in request path
5. **Access granted only if `sub` === `userId`**

### Key Security Features
- **JWT Signature Validation**: Uses Cognito's JWKS endpoint
- **Path Parameter Validation**: Ensures user can only access their own resources
- **User Agent Restrictions**: Demonstrates additional custom authorization logic
- **Fail-Safe**: Denies access on any validation error

## CloudFormation Resources

### Core Resources
- `AWS::Cognito::UserPool` - User authentication
- `AWS::Cognito::UserPoolClient` - Application client
- `AWS::Lambda::Function` - Custom authorizer logic
- `AWS::ApiGateway::RestApi` - API endpoint
- `AWS::ApiGateway::Authorizer` - Lambda authorizer integration

### IAM Roles
- **LambdaExecutionRole**: Basic execution + Cognito read access
- **ApiGatewayRole**: Lambda invocation permissions

## Demo Scenarios

### Valid Access (Should Succeed)
- User with `sub=abc123` accessing `/users/abc123`
- User with `sub=xyz789` accessing `/users/xyz789/orders`

### Invalid Access (Should Fail)  
- User with `sub=abc123` trying to access `/users/xyz789`
- User with `sub=xyz789` trying to access `/users/abc123/profile`
- Requests from curl/Postman user agents

## Implementation Notes

### Lambda Authorizer Code Structure
```python
# Extract userId from path
path_parts = method_arn.split('/')
user_id_from_path = extract_user_id(path_parts)

# Validate JWT and get sub
payload = jwt.decode(token, key, algorithms=['RS256'])
sub = payload.get('sub')

# Critical authorization check
if user_id_from_path and user_id_from_path != sub:
    return generate_policy('user', 'Deny', method_arn)
```

### API Gateway Integration
- Uses MOCK integration for demo simplicity
- Real implementation would proxy to EKS/backend services
- Context variables pass user info to backend: `$context.authorizer.sub`

## Deployment Instructions

### Prerequisites
- AWS CLI configured
- CloudFormation permissions
- Python 3.9+ for testing scripts

### Deploy Stack
```bash
aws cloudformation deploy \
  --template-file cloudformation/infrastructure.yaml \
  --stack-name cognito-demo \
  --capabilities CAPABILITY_IAM
```

### Test Setup
1. Create test users in Cognito User Pool
2. Authenticate users to get JWT tokens
3. Test API calls with different user tokens
4. Verify access control enforcement

## Key Learnings

### Why Lambda Authorizer vs Built-in Cognito Authorizer
- **Built-in**: Only validates JWT signature and scopes
- **Lambda**: Enables custom logic like `sub` to path parameter matching
- **Use Case**: Fine-grained authorization beyond scope-based access

### JWT Claims for Authorization
- **`sub`**: Unique user identifier, perfect for user-specific data access
- **`scope`**: API-level permissions (read/write)
- **Custom Claims**: Can be added via Pre Token Generation trigger

### Security Best Practices
- Always validate JWT signature
- Use HTTPS for all API communications
- Implement proper error handling (fail closed)
- Log authorization decisions for audit
- Consider token expiration and refresh strategies

## Future Enhancements
- Add EKS cluster with real backend services
- Implement scope-based authorization
- Add group-based access control
- Integrate with AWS Verified Permissions
- Add comprehensive logging and monitoring