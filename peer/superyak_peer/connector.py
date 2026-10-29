"""The remote connector (spec docs/superpowers/specs/2026-10-27-remote-connector-design.md): a person's home, read
from Claude through its own OAuth server and /mcp. Without `serve --public-origin`, none of it exists."""

DEFAULT_CALLBACK = 'https://claude.ai/api/mcp/auth_callback'  # claude.ai's; older help text said it may move to claude.com
SCOPES = ('rooms.read', 'offline_access')


def resource_metadata(issuer):
    """RFC 9728, at both protected-resource paths. offline_access stays out: MCP says resource servers SHOULD NOT list it."""
    return {'resource': issuer + '/mcp', 'authorization_servers': [issuer], 'bearer_methods_supported': ['header'],
            'scopes_supported': ['rooms.read']}


def issuer_metadata(issuer):
    """RFC 8414. code_challenge_methods_supported is required: without it MCP 2025-11-25 clients refuse to go on."""
    return {'issuer': issuer, 'authorization_endpoint': issuer + '/authorize', 'token_endpoint': issuer + '/token',
            'registration_endpoint': issuer + '/register', 'response_types_supported': ['code'],
            'grant_types_supported': ['authorization_code', 'refresh_token'],
            'token_endpoint_auth_methods_supported': ['none'], 'code_challenge_methods_supported': ['S256'],
            'scopes_supported': list(SCOPES), 'authorization_response_iss_parameter_supported': True}
