#!/usr/bin/env python3
"""
Demo script to test user-specific data protection
Shows how users can only access their own data
"""

import boto3
import requests
import json
import base64

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

def test_api_access(api_url, token, user_id, endpoint, expected_success=True):
    """Test API access with given token and user ID"""
    url = f"{api_url}/users/{user_id}"
    if endpoint:
        url += f"/{endpoint}"
    
    headers = {'Authorization': f'Bearer {token}'}
    
    try:
        response = requests.get(url, headers=headers, timeout=30)

        if expected_success and response.status_code == 200:
            print(f"✓ SUCCESS: Access granted to {endpoint or 'info'} for user {user_id[:8]}...")
            return True
        elif not expected_success and response.status_code == 403:
            print(f"✓ SUCCESS: Access denied to {endpoint or 'info'} for user {user_id[:8]}... (as expected)")
            return True
        else:
            # Raise for unexpected HTTP errors (5xx, unexpected 4xx)
            response.raise_for_status()
            print(f"✗ UNEXPECTED: {response.status_code} for {endpoint or 'info'} access to user {user_id[:8]}...")
            return False
            
    except requests.exceptions.RequestException as e:
        print(f"✗ ERROR: {e}")
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
        return
    
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
            # Simple JWT decode
            parts = token.split('.')
            payload_b64 = parts[1] + '=' * (4 - len(parts[1]) % 4)
            payload = json.loads(base64.b64decode(payload_b64))
            user_subs[user['username']] = payload['sub']
            print(f"✓ Got token for {user['username']} (sub: {payload['sub'][:8]}...)")
    
    # Test scenarios
    print("\nStep 3: Testing API access scenarios...")
    
    endpoints = [
        ('', 'User Info API', 'GET /users/{userId}'),
        ('orders', 'Orders API', 'GET /users/{userId}/orders'), 
        ('profile', 'Profile API', 'GET /users/{userId}/profile')
    ]
    
    for endpoint, api_name, api_path in endpoints:
        print(f"\n--- Testing {api_name} ({api_path}) ---")
        
        print(f"Test 1: User1 accessing their own data (Expected: ALLOW)")
        test_api_access(api_url, tokens['testuser1'], user_subs['testuser1'], endpoint, True)
        
        print(f"Test 2: User1 trying to access User2's data (Expected: DENY)")
        test_api_access(api_url, tokens['testuser1'], user_subs['testuser2'], endpoint, False)
    
    print("\nDemo completed successfully!")
    print("\nSummary: Users can only access their own data via sub claim validation")

if __name__ == "__main__":
    run_demo()