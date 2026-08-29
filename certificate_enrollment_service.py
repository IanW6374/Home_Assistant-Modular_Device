"""Runtime certificate-method changes initiated from the authenticated portal."""

try:
    import uasyncio as asyncio
except ImportError:
    import asyncio
try:
    import uos as os
except ImportError:
    import os

import certificate_manager
import credential_store
import iot_ca_enrollment
import setup_workflow


ENROLLMENT_UPLOAD_PATH = 'certs/.iot-ca-enrollment.manual'
STATUS = {'status': 'idle', 'message': '', 'mode': ''}


def snapshot():
    return dict(STATUS)


def _config():
    value = credential_store.load(require_provisioned=True)
    certificate = value.setdefault('certificate', {})
    certificate.setdefault(
        'hostname', str(value.get('device_name', 'iot-md-001')) + '.local'
    )
    return value


async def _finish(operation, reload_identities):
    await operation
    if STATUS.get('status') == 'complete':
        reload_identities()


def change(method, params, paths, reload_portal, reload_identities):
    method = str(method or '').strip()
    if STATUS.get('status') == 'running':
        raise ValueError('a certificate enrollment is already running')
    config = _config()
    hostname = config['certificate']['hostname']
    if method == 'self_signed':
        certificate_manager.install_self_signed(hostname)
        credential_store.update_certificate_settings(
            'self_signed', hostname=hostname, portal_hostname=hostname,
            method='self_signed'
        )
        STATUS.update({
            'status': 'complete', 'mode': method,
            'message': 'Self-signed device certificate installed; portal HTTPS is reloading',
        })
        reload_portal()
        return STATUS['message']
    if method == 'iot_ca_auto':
        server = iot_ca_enrollment._auto_server(params.get('ca_server', ''))
        port = iot_ca_enrollment._auto_port(params.get('ca_port', ''))
        STATUS.update({'status': 'running', 'mode': method, 'message': 'Starting IoT CA enrollment'})
        operation = iot_ca_enrollment.automatic_install(
            server, config, paths, setup_workflow._connect_station,
            setup_workflow._validate_certificates, STATUS, port
        )
    elif method == 'iot_ca_file':
        try:
            with open(ENROLLMENT_UPLOAD_PATH, 'rb') as stream:
                payload = stream.read()
        except OSError:
            raise ValueError('select and upload an IoT CA enrollment authorization first')
        STATUS.update({'status': 'running', 'mode': method, 'message': 'Starting IoT CA enrollment'})
        operation = iot_ca_enrollment.install(
            payload, config, paths, setup_workflow._connect_station,
            setup_workflow._validate_certificates, STATUS
        )
        try:
            os.remove(ENROLLMENT_UPLOAD_PATH)
        except OSError:
            pass
    else:
        raise ValueError('unsupported certificate enrollment method')
    asyncio.create_task(_finish(operation, reload_identities))
    return 'Certificate enrollment started; this page will show its progress'
