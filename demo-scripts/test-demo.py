#!/usr/bin/env python3
"""
Demo script to test user-specific data protection
Shows how users can only access their own data
"""

import boto3
import requests
import json
import base64
import sys

def create_test_users(cognito_client, user_pool_id):
    """Create two test users"""
    users = [
        {'username': 'testuser1', 'password': 'TempPass123!', 'email': 'user1@example.com'},
        {'username': 'testuser2', 'password': 'TempPass123!', 'email': 'user2@example.com'}
    ]
    
    for user in users:
        try:
            cognito_client.admin_create_user(
                UserPoolId=user_pool_id,
                Username=user['username'],
                TemporaryPassword=user['password'],
                MessageAction='SUPPRESS',
                UserAttributes=[
                    {'Name': 'email', 'Value': user['email']},
                    {'Name': 'email_verified', 'Value': 'true'}
                ]
            )
            
            cognito_client.admin_set_user_password(
                UserPoolId=user_pool_id,
                Username=user['username'],
                Password=user['password'],
                Permanent=True
            )
            
            print(f"✓ Created user: {user['username']}")
            
        except cognito_client.exceptions.UsernameExistsException:
            print(f"✓ User already exists: {user['username']}")
    
    return users

def get_access_token(cognito_client, user_pool_id, client_id, username, password):
    """Get access token for user"""
    try:
        response = cognito_client.admin_initiate_auth(
            UserPoolId=user_pool_id,
            ClientId=client_id,
            AuthFlow='ADMIN_NO_SRP_AUTH',
            AuthParameters={
                'USERNAME': username,
                'PASSWORD': password
            }
        )
        return response['AuthenticationResult']['AccessToken']
    except Exception as e:
        print(f"Failed to get token for {username}: {e}")
        return None

def b64url_json(obj):
    return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip('=')

def decode_jwt_claims(token):
    """Read claims from a token we just received from Cognito (display only, not verification)."""
    payload_b64 = token.split('.')[1]
    payload_b64 += '=' * (-len(payload_b64) % 4)
    return json.loads(base64.urlsafe_b64decode(payload_b64))

def forge_token(real_token):
    """
    Copy a real token's claims, swap in a different `sub`, and attach a
    made-up signature. A correct authorizer must reject this with 401.
    """
    header_b64, _, _ = real_token.split('.')
    claims = decode_jwt_claims(real_token)
    claims['sub'] = 'forged-' + claims['sub']
    return f"{header_b64}.{b64url_json(claims)}.totally-fake-signature"

def test_api_access(api_url, token, user_id, endpoint, expected_status):
    """Call the API and check the HTTP status. Returns True if it matched."""
    url = f"{api_url}/users/{user_id}"
    if endpoint:
        url += f"/{endpoint}"

    headers = {'Authorization': f'Bearer {token}'} if token is not None else {}
    label = f"{endpoint or 'info'} for user {user_id[:8]}..."

    try:
        response = requests.get(url, headers=headers, timeout=30)
    except requests.exceptions.RequestException as e:
        print(f"✗ ERROR: {e}")
        return False

    if response.status_code == expected_status:
        print(f"✓ PASS: {response.status_code} for {label}")
        return True
    print(f"✗ FAIL: expected {expected_status}, got {response.status_code} for {label}")
    return False

def run_demo():
    """Run the complete demo"""
    print("Starting User-Specific Data Protection Demo\n")
    
    # Get stack outputs
    cf_client = boto3.client('cloudformation')
    try:
        response = cf_client.describe_stacks(StackName='cognito-demo-authorizer-v2')
        outputs = {output['OutputKey']: output['OutputValue'] 
                  for output in response['Stacks'][0]['Outputs']}
        
        user_pool_id = outputs['UserPoolId']
        client_id = outputs['UserPoolClientId']
        api_url = outputs['ApiGatewayUrl']
        
    except Exception as e:
        print(f"❌ Failed to get stack outputs: {e}")
        print("Make sure the CloudFormation stack 'cognito-demo-authorizer-v2' is deployed")
        sys.exit(1)
    
    cognito_client = boto3.client('cognito-idp')
    
    # Create test users
    print("Step 1: Creating test users...")
    users = create_test_users(cognito_client, user_pool_id)
    
    # Get tokens for both users
    print("\nStep 2: Getting access tokens...")
    tokens = {}
    user_subs = {}
    
    for user in users:
        token = get_access_token(cognito_client, user_pool_id, client_id, user['username'], user['password'])
        if token:
            tokens[user['username']] = token
            payload = decode_jwt_claims(token)
            user_subs[user['username']] = payload['sub']
            print(f"✓ Got token for {user['username']} (sub: {payload['sub'][:8]}...)")
    
    # Test scenarios
    print("\nStep 3: Testing API access scenarios...")
    
    endpoints = [
        ('', 'User Info API', 'GET /users/{userId}'),
        ('orders', 'Orders API', 'GET /users/{userId}/orders'), 
        ('profile', 'Profile API', 'GET /users/{userId}/profile')
    ]
    
    if 'testuser1' not in tokens or 'testuser2' not in tokens:
        print("❌ Could not get tokens for both test users")
        sys.exit(1)

    results = []
    user1, user2 = user_subs['testuser1'], user_subs['testuser2']
    forged = forge_token(tokens['testuser1'])

    for endpoint, api_name, api_path in endpoints:
        print(f"\n--- Testing {api_name} ({api_path}) ---")

        print("Test 1: User1 accessing their own data (Expected: 200)")
        results.append(test_api_access(api_url, tokens['testuser1'], user1, endpoint, 200))

        print("Test 2: User1 trying to access User2's data (Expected: 403)")
        results.append(test_api_access(api_url, tokens['testuser1'], user2, endpoint, 403))

        print("Test 3: No Authorization header (Expected: 401)")
        results.append(test_api_access(api_url, None, user1, endpoint, 401))

        print("Test 4: Forged token with fake signature (Expected: 401)")
        results.append(test_api_access(api_url, forged, 'forged-' + user1, endpoint, 401))

    passed = sum(results)
    print(f"\n{passed}/{len(results)} checks passed")
    if passed != len(results):
        print("❌ Demo FAILED: authorization did not behave as expected")
        sys.exit(1)

    print("Demo completed successfully!")
    print("\nSummary: Only validly signed tokens are accepted, and users can only access their own data")

if __name__ == "__main__":
    run_demo()