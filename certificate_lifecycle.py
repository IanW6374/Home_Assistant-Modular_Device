"""Start the renewal strategy owned by the selected certificate method."""

import certificate_manager
import iot_ca_enrollment
import setup_workflow


async def monitor(config, paths, log_output, reload_portal, reload_identity_set):
    mode = str(config.get('mode', 'manual'))
    if mode == 'acme':
        await certificate_manager.renewal_monitor(
            config, paths['trust-ca'], log_output, reload_portal
        )
    elif mode == 'iot_ca':
        await iot_ca_enrollment.renewal_monitor(
            config, paths, setup_workflow._validate_certificates,
            log_output, reload_identity_set
        )
    elif mode == 'self_signed':
        await certificate_manager.self_signed_renewal_monitor(
            config, log_output, reload_portal
        )
    elif mode == 'manual':
        log_output(
            'Local', 'Manual certificate package',
            {'log': 'Automatic renewal is unavailable. Replace the public portal and '
                    'private Device API/fleet certificates before either identity expires.',
             'force': True},
            'INFO'
        )
