# Cognito Authorization Demo

This project demonstrates user-specific data protection using Amazon Cognito, API Gateway, Lambda authorizer, and EKS. The core security principle is simple: users can only access their own data. Any attempt to access another user's data gets denied automatically.

## Architecture

```
User → Cognito Authentication → API Gateway → Lambda Authorizer → EKS APIs
```

## Security Features

- Users can only access data where the userId in the URL matches their sub claim from the JWT token
- Lambda authorizer validates Cognito JWT tokens and enforces access control
- Custom authorization logic that goes beyond basic API Gateway features
- Prevents cross-user data access attempts

## API Endpoints

- `GET /users/{userId}` - Get user information
- `GET /users/{userId}/orders` - Get user orders  
- `GET /users/{userId}/profile` - Get user profile

## Getting Started

### Prerequisites
- AWS CLI configured with appropriate permissions
- kubectl installed for EKS management
- Python 3.x for running the demo script

### Deployment

1. Deploy the infrastructure:
   ```bash
   ./deploy.sh
   ```

2. Optionally deploy APIs to EKS:
   ```bash
   ./deploy-eks-apis.sh
   ```

3. Run the demonstration:
   ```bash
   python3 demo-scripts/test-demo.py
   ```

## Demo Scenarios

The demo creates two test users and shows three key scenarios:

1. User1 accessing their own orders - Access granted
2. User1 trying to access User2's orders - Access denied  
3. User2 accessing their own profile - Access granted

## How Authorization Works

The Lambda authorizer implements this logic:

```python
# Extract userId from the API request path
user_id_from_path = extract_from_path(method_arn)

# Decode the JWT token to get the user's actual identity
payload = jwt_decode(token)
sub = payload.get('sub')

# Only allow access if the path userId matches the token's sub claim
if user_id_from_path != sub:
    return generate_policy('user', 'Deny', method_arn)
```

## Project Structure

```
cloudformation/
  infrastructure.yaml    # AWS resources definition
demo-scripts/
  test-demo.py          # Automated testing script
k8s/
  apis.yaml             # Kubernetes service definitions
deploy.sh               # Infrastructure deployment
deploy-eks-apis.sh      # EKS services deployment
cleanup.sh              # Resource cleanup
requirements.txt        # Python dependencies
```

## Cleanup

To remove all created resources:

```bash
./cleanup.sh
```

This removes the CloudFormation stack including the EKS cluster, Cognito resources, API Gateway, Lambda functions, and Kubernetes deployments.

## Manual Testing

You can test the authorization manually:

1. Get an access token:
   ```bash
   aws cognito-idp admin-initiate-auth \
     --user-pool-id <USER_POOL_ID> \
     --client-id <CLIENT_ID> \
     --auth-flow ADMIN_NO_SRP_AUTH \
     --auth-parameters USERNAME=testuser1,PASSWORD=TempPass123!
   ```

2. Test API access:
   ```bash
   # This should work (user accessing own data)
   curl -H "Authorization: Bearer <TOKEN>" \
     https://<API_ID>.execute-api.<REGION>.amazonaws.com/dev/users/<USER1_SUB>

   # This should fail (user accessing other's data)  
   curl -H "Authorization: Bearer <TOKEN>" \
     https://<API_ID>.execute-api.<REGION>.amazonaws.com/dev/users/<USER2_SUB>
   ```

## Technical Notes

- Infrastructure is defined using CloudFormation for reproducible deployments
- The demo uses mock API integrations that return user-specific data based on the sub claim
- EKS deployment is optional - the authorization concept works with any backend
- Focus is on demonstrating fine-grained authorization patterns in AWS