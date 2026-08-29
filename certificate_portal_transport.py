"""HTTP adapter for certificate portal routes."""

from portal_http import apply_portal_action
from certificate_portal_views import render_certificate_route


async def handle(method, route, path, writer, reader, headers, form, csrf,
                 actions, log_output, upload, validate, inventory,
                 send_response, send_redirect):
    certificate_routes = (
        '/certificates', '/certificate-authorities',
        '/api-client-trust', '/device-certificates'
    )
    if method == 'GET' and route in certificate_routes:
        await send_response(writer, '200 OK', render_certificate_route(
            route, csrf, certificates=inventory() if inventory else {}
        ))
        return True
    if method == 'POST' and route == '/remove-certificate-trust':
        apply_portal_action(
            'remove-certificate-trust', path, actions, log_output, form
        )
        target = form.get('return_to', '/certificate-authorities')
        await send_redirect(writer, target if target in certificate_routes else '/certificate-authorities')
        return True
    if method == 'POST' and route == '/certificate-method':
        result = apply_portal_action(
            'certificate-method', path, actions, log_output, form
        )
        message = result.get('message', '') if isinstance(result, dict) else result
        await send_response(writer, '202 Accepted', render_certificate_route(
            '/certificates', csrf, message, inventory() if inventory else {}
        ))
        return True
    if method == 'POST' and path.startswith('/certificate-upload'):
        if upload is None:
            await send_response(writer, '503 Service Unavailable', 'Certificate upload is unavailable', 'text/plain')
            return True
        length = int(headers.get('content-length', '0') or 0)
        if length <= 0 or length > 16384:
            raise ValueError('certificate file size is invalid')
        await upload(headers.get('x-certificate-kind', ''), reader, length)
        await send_response(writer, '200 OK', 'Certificate file stored', 'text/plain')
        return True
    if method == 'POST' and route == '/validate-certificates':
        try:
            if validate is None:
                raise RuntimeError('certificate validation is unavailable')
            result = validate()
        except Exception as exc:
            await send_response(writer, '400 Bad Request', str(exc), 'text/plain')
        else:
            message = result.get('message', '') if isinstance(result, dict) else str(result)
            target = form.get('return_to', '/device-certificates')
            await send_response(writer, '200 OK', render_certificate_route(
                target, csrf, message, inventory() if inventory else {}
            ))
        return True
    return False
