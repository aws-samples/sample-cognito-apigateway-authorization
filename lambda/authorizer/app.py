"""
API Gateway TOKEN authorizer for Amazon Cognito access tokens.

Every request is authenticated by cryptographically verifying the JWT
signature against the user pool's JWKS before any claim is trusted.
Only after verification does the authorizer read `sub` and scope the
returned policy to that user's own resources.

References:
  https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-using-tokens-verifying-a-jwt.html
  https://docs.aws.amazon.com/apigateway/latest/developerguide/apigateway-lambda-authorizer-output.html
"""

import os
import re

import jwt
from jwt import PyJWKClient

REGION = os.environ['REGION']
USER_POOL_ID = os.environ['USER_POOL_ID']
APP_CLIENT_ID = os.environ['APP_CLIENT_ID']

ISSUER = 'https://cognito-idp.{}.amazonaws.com/{}'.format(REGION, USER_POOL_ID)
JWKS_URL = ISSUER + '/.well-known/jwks.json'

# Cognito signs tokens with RS256 only. Pinning the algorithm prevents
# algorithm-confusion attacks (e.g. "alg": "none" or HS256 with the public key).
ALLOWED_ALGORITHMS = ['RS256']

# Cognito `sub` values are UUIDs. Rejecting anything else keeps the value
# safe to embed in the policy's resource ARN (no '*', '/', or '?').
SUB_PATTERN = re.compile(r'^[0-9A-Za-z-]{1,128}$')

# Created once per execution environment so the JWKS is cached across
# invocations. PyJWKClient refetches the key set when it sees an unknown `kid`,
# which handles Cognito key rotation.
_jwks_client = PyJWKClient(JWKS_URL, cache_keys=True, lifespan=3600, timeout=5)


def extract_bearer_token(authorization_header):
    """Return the token from an 'Authorization: Bearer <token>' header value."""
    parts = (authorization_header or '').split()
    if len(parts) != 2 or parts[0].lower() != 'bearer':
        raise ValueError('Missing or malformed Authorization header')
    return parts[1]


def verify_access_token(token):
    """
    Verify a Cognito access token and return its claims.

    Raises jwt.PyJWTError (or ValueError) if the token is not a valid,
    unexpired access token issued by this user pool for this app client.
    """
    # Looks up the public key by the token header's `kid`. Unknown kids fail.
    signing_key = _jwks_client.get_signing_key_from_jwt(token)

    # Verifies signature, `exp`, `iat`, and `iss`. Access tokens carry no `aud`
    # claim (the app client is in `client_id`), which PyJWT accepts when no
    # audience is requested.
    claims = jwt.decode(
        token,
        signing_key.key,
        algorithms=ALLOWED_ALGORITHMS,
        issuer=ISSUER,
        options={'require': ['exp', 'iat', 'iss', 'sub', 'token_use', 'client_id']},
    )

    # ID tokens are signed by the same keys, so check the token type explicitly.
    if claims['token_use'] != 'access':
        raise ValueError('Token is not an access token')

    if claims['client_id'] != APP_CLIENT_ID:
        raise ValueError('Token was not issued for this app client')

    if not SUB_PATTERN.match(claims['sub']):
        raise ValueError('Unexpected sub format')

    return claims


def user_resource_arns(method_arn, sub):
    """
    Build the resources this user may invoke: /users/{sub} and everything below it.

    methodArn format:
      arn:aws:execute-api:{region}:{account}:{apiId}/{stage}/{httpVerb}/{resource...}

    The policy is scoped to the caller's own paths instead of the exact
    methodArn because API Gateway caches the authorizer result per token
    (AuthorizerResultTtlInSeconds). A cached policy must stay correct for every
    path the same token is later used on: the user's own paths are allowed,
    and any other user's path is outside the policy, so API Gateway returns
    403 without invoking the authorizer again.
    """
    arn_parts = method_arn.split('/')
    if len(arn_parts) < 3:
        raise ValueError('Unexpected methodArn format')
    api_stage_arn = '/'.join(arn_parts[:2])  # arn:...:{apiId}/{stage}
    return [
        '{}/GET/users/{}'.format(api_stage_arn, sub),
        '{}/GET/users/{}/*'.format(api_stage_arn, sub),
    ]


def generate_policy(principal_id, effect, resources):
    return {
        'principalId': principal_id,
        'policyDocument': {
            'Version': '2012-10-17',
            'Statement': [{
                'Action': 'execute-api:Invoke',
                'Effect': effect,
                'Resource': resources,
            }],
        },
        'context': {
            'sub': principal_id,
        },
    }


def handler(event, context):
    try:
        token = extract_bearer_token(event.get('authorizationToken'))
        claims = verify_access_token(token)
        sub = claims['sub']
        return generate_policy(sub, 'Allow', user_resource_arns(event['methodArn'], sub))
    except Exception as e:  # noqa: BLE001 - every failure must map to 401
        # Never log the token itself.
        print('Authorization failed: {}: {}'.format(type(e).__name__, e))
        # This exact message makes API Gateway return 401 Unauthorized.
        raise Exception('Unauthorized')
