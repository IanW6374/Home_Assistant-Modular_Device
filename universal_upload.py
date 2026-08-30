"""Low-storage, sequential transport for signed universal updates.

The release container still binds the application and core as one signed
release.  Transporting the two inner bundles sequentially avoids retaining the
combined container on the device filesystem.
"""

try:
    import ujson as json
except ImportError:
    import json

try:
    import uos as os
except ImportError:
    import os

import app_update
import firmware_update
import universal_update
import update_security
import update_support


PLAN_PATH = '.universal-upload-plan.json'
PLAN_FORMAT_VERSION = 1
SUPPORTED_CONTAINER_FORMATS = (2, 3)


def _remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


def _replace(source, target):
    _remove(target)
    os.rename(source, target)


def _write_plan(plan):
    temporary = PLAN_PATH + '.tmp'
    with open(temporary, 'w') as stream:
        json.dump(plan, stream)
    _replace(temporary, PLAN_PATH)


def _load_plan():
    try:
        with open(PLAN_PATH, 'r') as stream:
            value = json.load(stream)
        if (
            isinstance(value, dict) and
            int(value.get('format_version', 0)) == PLAN_FORMAT_VERSION
        ):
            return value
    except Exception:
        pass
    return {}


def _digest(value):
    value = str(value).lower()
    if len(value) != 64 or any(
        character not in '0123456789abcdef' for character in value
    ):
        raise ValueError('universal component SHA-256 is invalid')
    return value


def _validate_v3_manifest(manifest):
    """Validate format 3 on the v2.2.0 bridge core.

    That core understands the same signed fields but intentionally accepts only
    format 2 through its public validator.  The format number itself is part of
    the signed canonical message, so verifying it here does not weaken the
    release binding.
    """
    if not isinstance(manifest, dict):
        raise ValueError('universal manifest must be an object')
    if int(manifest.get('format_version', 0)) != 3:
        raise ValueError('unsupported universal update format')
    if str(manifest.get('target_board', '')) != update_security.TARGET_BOARD:
        raise ValueError('universal update target board is not supported')
    version = str(manifest.get('version', '')).strip()
    sequence = int(manifest.get('release_sequence', 0))
    if not version or sequence <= 0:
        raise ValueError('universal update version is invalid')
    for name in ('firmware', 'application'):
        component = manifest.get(name)
        if not isinstance(component, dict):
            raise ValueError('universal update has no ' + name + ' component')
        if str(component.get('version', '')).strip() != version:
            raise ValueError('universal component version labels do not match')
        if int(component.get('release_sequence', 0)) != sequence:
            raise ValueError('universal component release sequences do not match')
        if int(component.get('size', 0)) <= 0:
            raise ValueError('universal ' + name + ' size is invalid')
        _digest(component.get('sha256', ''))
    if manifest.get('activation_order') not in (
        ['application', 'firmware'], ['firmware', 'application']
    ):
        raise ValueError('universal activation order is invalid')
    if not isinstance(manifest.get('maintenance_required'), bool):
        raise ValueError('universal maintenance policy is invalid')
    if manifest.get('rollback_policy') not in ('paired', 'independent', 'manual'):
        raise ValueError('universal rollback policy is invalid')
    timeout = int(manifest.get('trial_timeout_s', 0))
    if timeout < 30 or timeout > 3600:
        raise ValueError('universal trial timeout is invalid')
    signature = str(manifest.get('signature', '')).lower()
    public_key = update_security._public_key()
    if (
        public_key is None or
        manifest.get('signature_scheme') != update_security.SIGNATURE_SCHEME or
        len(signature) != 128 or
        not update_security.verify_manifest_signature(
            'iotuni', manifest, signature, public_key
        )
    ):
        raise ValueError('universal update signature verification failed')
    return {'signed': True, 'required': True}


def validate_manifest(manifest):
    format_version = int(
        manifest.get('format_version', 0) if isinstance(manifest, dict) else 0
    )
    if format_version not in SUPPORTED_CONTAINER_FORMATS:
        raise ValueError('unsupported universal update format')
    if format_version == 3:
        try:
            return update_security.validate_universal_manifest(manifest)
        except ValueError as exc:
            if 'unsupported universal update format' not in str(exc):
                raise
            return _validate_v3_manifest(manifest)
    return update_security.validate_universal_manifest(manifest)


def _plan_identifier(manifest):
    signature = str(manifest.get('signature', '')).lower()
    if len(signature) != 128:
        raise ValueError('universal update signature is invalid')
    return signature[:32]


def _component_plan(manifest, name, running_sequence):
    component = manifest[name]
    required = int(running_sequence) < int(component['release_sequence'])
    return {
        'required': required,
        'complete': not required,
        'upload_id': '',
        'size': int(component['size']),
        'sha256': _digest(component['sha256']),
        'version': str(component['version']),
        'release_sequence': int(component['release_sequence']),
    }


def prepare(manifest):
    """Create a persistent plan from a verified outer universal manifest."""
    validate_manifest(manifest)
    identifier = _plan_identifier(manifest)
    existing = _load_plan()
    if (
        existing and str(existing.get('id', '')) == identifier and
        str(existing.get('manifest', {}).get('signature', '')) ==
        str(manifest.get('signature', ''))
    ):
        return status(identifier)
    # A paired rollback may complete before the universal coordinator gets an
    # opportunity to remove its state file.  Reconcile that terminal state so
    # a remote administrator can immediately retry without USB intervention.
    universal_update.reconcile_pending()
    universal_state = universal_update.update_status()
    if universal_state.get('status', 'idle') != 'idle':
        raise ValueError('another universal update is already pending')
    application_sequence = app_update.running_release_sequence()
    firmware_sequence = firmware_update.running_release_sequence()
    offered_sequence = int(manifest.get('release_sequence', 0))
    if (
        int(application_sequence) > offered_sequence or
        int(firmware_sequence) > offered_sequence
    ):
        raise ValueError(
            'universal update is older than an installed component'
        )
    application = _component_plan(
        manifest, 'application', application_sequence
    )
    firmware = _component_plan(
        manifest, 'firmware', firmware_sequence
    )
    if not application['required'] and not firmware['required']:
        raise ValueError('universal update is not newer than the installed release')
    if application['required'] and app_update.update_status().get('status') != 'idle':
        raise ValueError('another application update is already pending')
    if firmware['required'] and firmware_update.update_status().get('status') != 'idle':
        raise ValueError('another core firmware update is already pending')
    plan = {
        'format_version': PLAN_FORMAT_VERSION,
        'id': identifier,
        'manifest': manifest,
        'application': application,
        'firmware': firmware,
    }
    _write_plan(plan)
    update_support.record_update_event(
        'universal', 'transport_ready', str(manifest.get('version', '')),
        detail='sequential component transport'
    )
    return status(plan['id'])


def status(identifier=''):
    plan = _load_plan()
    if not plan:
        return {'status': 'idle'}
    if identifier and str(identifier) != str(plan.get('id', '')):
        raise ValueError('universal upload plan does not exist')
    result = {
        'status': 'uploading',
        'id': str(plan.get('id', '')),
        'version': str(plan.get('manifest', {}).get('version', '')),
    }
    for name in ('firmware', 'application'):
        component = plan.get(name, {})
        result[name] = {
            key: component.get(key)
            for key in (
                'required', 'complete', 'size', 'sha256', 'version',
                'release_sequence'
            )
        }
    return result


def authorize_upload(request):
    """Bind a resumable inner upload to the signed persistent plan."""
    if not isinstance(request, dict):
        raise ValueError('resumable upload request is invalid')
    plan = _load_plan()
    identifier = str(request.get('universal_plan', ''))
    if not plan or identifier != str(plan.get('id', '')):
        raise ValueError('universal upload plan does not exist')
    kind = str(request.get('kind', ''))
    if kind not in ('application', 'firmware'):
        raise ValueError('universal component type is invalid')
    component = plan.get(kind, {})
    if not component.get('required'):
        raise ValueError('universal component is already installed')
    if int(request.get('total_bytes', 0)) != int(component.get('size', 0)):
        raise ValueError('universal component size does not match its manifest')
    if _digest(request.get('sha256', '')) != component.get('sha256'):
        raise ValueError('universal component SHA-256 does not match its manifest')
    upload_id = str(request.get('id', ''))
    existing = str(component.get('upload_id', ''))
    if existing and existing != upload_id and not component.get('complete'):
        raise ValueError('a different upload is already bound to this component')
    component['upload_id'] = upload_id
    plan[kind] = component
    _write_plan(plan)
    return True


def begin(begin_callback, request):
    if isinstance(request, dict) and request.get('universal_plan'):
        authorize_upload(request)
    return begin_callback(request)


def mark_complete(upload_id, kind):
    plan = _load_plan()
    kind = str(kind)
    if not plan or kind not in ('application', 'firmware'):
        return False
    component = plan.get(kind, {})
    if str(component.get('upload_id', '')) != str(upload_id):
        return False
    state = (
        app_update.update_status() if kind == 'application'
        else firmware_update.update_status()
    )
    if (
        state.get('status') != 'ready' or
        str(state.get('version', '')) != str(component.get('version', '')) or
        int(state.get('release_sequence', 0)) !=
        int(component.get('release_sequence', 0))
    ):
        raise ValueError('staged universal component metadata does not match')
    component['complete'] = True
    plan[kind] = component
    _write_plan(plan)
    return True


def completed_result(upload_id, kind, result):
    mark_complete(upload_id, kind)
    return result


def finalize(identifier):
    plan = _load_plan()
    if not plan or str(identifier) != str(plan.get('id', '')):
        raise ValueError('universal upload plan does not exist')
    manifest = plan.get('manifest', {})
    validate_manifest(manifest)
    for name in ('firmware', 'application'):
        component = plan.get(name, {})
        if component.get('required') and not component.get('complete'):
            raise ValueError('universal ' + name + ' upload is incomplete')
        if not component.get('required'):
            running = (
                firmware_update.running_release_sequence()
                if name == 'firmware'
                else app_update.running_release_sequence()
            )
            if int(running) != int(component.get('release_sequence', 0)):
                raise ValueError(
                    'installed universal ' + name + ' component has changed'
                )
    stage = getattr(universal_update, 'stage_preverified', None)
    if stage:
        state = stage(
            manifest,
            bool(plan['firmware'].get('required')),
            bool(plan['application'].get('required')),
        )
    else:
        # Compatibility bridge for the v2.2.0 frozen updater.  Every field was
        # signature-validated above and each required inner bundle has passed
        # its normal signed installer before this state is written.
        state = {
            'status': 'ready',
            'version': str(manifest.get('version', '')),
            'release_sequence': int(manifest.get('release_sequence', 0)),
            'firmware_version': str(manifest['firmware'].get('version', '')),
            'firmware_sequence': int(manifest['firmware'].get('release_sequence', 0)),
            'application_version': str(manifest['application'].get('version', '')),
            'application_sequence': int(manifest['application'].get('release_sequence', 0)),
            'firmware_required': bool(plan['firmware'].get('required')),
            'application_required': bool(plan['application'].get('required')),
            'activation_order': list(manifest.get('activation_order', ())),
            'maintenance_required': bool(manifest.get('maintenance_required')),
            'rollback_policy': str(manifest.get('rollback_policy', 'paired')),
            'trial_timeout_s': int(manifest.get('trial_timeout_s', 180)),
        }
        temporary = universal_update.STATE_PATH + '.tmp'
        with open(temporary, 'w') as stream:
            json.dump(state, stream)
        _replace(temporary, universal_update.STATE_PATH)
        update_support.record_update_event(
            'universal', 'staged', state['version'],
            detail='sequential component transport'
        )
    _remove(PLAN_PATH)
    return state


def discard():
    existed = bool(_load_plan())
    _remove(PLAN_PATH)
    _remove(PLAN_PATH + '.tmp')
    return existed


def cleanup_interrupted():
    _remove(PLAN_PATH + '.tmp')
