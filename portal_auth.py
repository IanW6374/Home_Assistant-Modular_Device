"""Bounded role-based portal identity management for HAMD v2."""

try:
    import uos as os
except ImportError:
    import os

import credential_security
import credential_store


ROLE_LEVELS = {'viewer': 10, 'operator': 20, 'administrator': 30}
VIEWER_ROUTES = {
    '/', '/partials', '/diagnostics', '/logging', '/health-history',
    '/task-status', '/update-progress',
}
OPERATOR_ROUTES = {
    '/updates', '/check-release', '/download-release', '/update-upload',
    '/firmware-upload', '/universal-upload', '/activate-update',
    '/activate-firmware', '/activate-universal', '/rollback-application',
    '/calibrate', '/discover', '/ems-debug', '/trigger-discovery',
    '/display-loglevel',
    '/resumable-upload-begin', '/resumable-upload-status',
    '/resumable-upload-chunk', '/resumable-upload-complete',
}


def role_allows(role, required):
    return ROLE_LEVELS.get(str(role), -1) >= ROLE_LEVELS.get(str(required), 999)


def required_role(method, route):
    route = str(route).split('?', 1)[0]
    method = str(method).upper()
    if route in VIEWER_ROUTES and method == 'GET':
        return 'viewer'
    if route in OPERATOR_ROUTES:
        return 'operator'
    return 'administrator'


def _find(config, username):
    folded = str(username).lower()
    return next((
        user for user in config.get('portal', {}).get('users', ())
        if str(user.get('username', '')).lower() == folded
    ), None)


def list_users():
    config = credential_store.load(require_provisioned=True)
    return [{
        'username': user['username'], 'role': user['role'],
        'enabled': bool(user['enabled'])
    } for user in config['portal']['users']]


async def authenticate(username, password):
    config = credential_store.load(require_provisioned=True)
    user = _find(config, username)
    if not user or not user.get('enabled'):
        return None
    if not await credential_security.verify_password_async(
        password, user.get('password_verifier', '')
    ):
        return None
    return {'username': user['username'], 'role': user['role']}


def add_user(username, password, role='viewer'):
    username = str(username).strip()
    role = str(role)
    credential_security.validate_password_strength(password)
    config = credential_store.load(require_provisioned=True)
    if _find(config, username):
        raise ValueError('portal username already exists')
    users = config['portal']['users']
    if len(users) >= credential_store.MAX_PORTAL_USERS:
        raise ValueError('portal user limit reached')
    if role not in credential_store.PORTAL_ROLES:
        raise ValueError('portal user role is invalid')
    verifier = credential_security.password_verifier(
        password, os.urandom(credential_security.PASSWORD_SALT_BYTES)
    )
    users.append({
        'username': username, 'password_verifier': verifier,
        'role': role, 'enabled': True,
    })
    credential_store.save(config)
    return {'username': username, 'role': role, 'enabled': True}


def update_user(username, role=None, enabled=None, password=None):
    config = credential_store.load(require_provisioned=True)
    user = _find(config, username)
    if not user:
        raise ValueError('portal user does not exist')
    administrators = [
        item for item in config['portal']['users']
        if item.get('role') == 'administrator' and item.get('enabled')
    ]
    removes_last_administrator = (
        user.get('role') == 'administrator' and user.get('enabled') and
        ((role is not None and str(role) != 'administrator') or enabled is False)
    )
    if removes_last_administrator and len(administrators) <= 1:
        raise ValueError('at least one enabled portal administrator is required')
    if role is not None:
        role = str(role)
        if role not in credential_store.PORTAL_ROLES:
            raise ValueError('portal user role is invalid')
        user['role'] = role
    if enabled is not None:
        user['enabled'] = bool(enabled)
    if password is not None:
        credential_security.validate_password_strength(password)
        user['password_verifier'] = credential_security.password_verifier(
            password, os.urandom(credential_security.PASSWORD_SALT_BYTES)
        )
    credential_store.save(config)
    return {
        'username': user['username'], 'role': user['role'],
        'enabled': user['enabled']
    }


def remove_user(username):
    config = credential_store.load(require_provisioned=True)
    users = config['portal']['users']
    target = _find(config, username)
    if not target:
        return False
    if (
        target.get('role') == 'administrator' and target.get('enabled') and
        len([
            item for item in users
            if item.get('role') == 'administrator' and item.get('enabled')
        ]) <= 1
    ):
        raise ValueError('at least one enabled portal administrator is required')
    users.remove(target)
    credential_store.save(config)
    return True
