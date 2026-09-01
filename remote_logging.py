"""Bounded RFC 5424 remote syslog delivery over UDP or authenticated TLS."""

try:
    import uasyncio as asyncio
except ImportError:
    import asyncio

try:
    import usocket as socket
except ImportError:
    import socket

try:
    import ussl as ssl
except ImportError:
    import ssl

import http_support
from tls_sessions import TLSSessionHandle, open_tls_connection


SEVERITY = {'ERROR': 3, 'INFO': 6, 'DEBUG': 7}
FACILITY_LOCAL0 = 16


def rfc5424_message(timestamp, hostname, application, message, severity='INFO'):
    priority = (FACILITY_LOCAL0 * 8) + SEVERITY.get(str(severity).upper(), 6)
    timestamp = str(timestamp or '-').replace(' ', 'T')
    if timestamp != '-' and not timestamp.endswith('Z'):
        timestamp += 'Z'
    safe_host = str(hostname or '-')[:64].replace(' ', '_')
    safe_app = str(application or 'IoT-MD')[:48].replace(' ', '_')
    safe_message = str(message).replace('\r', ' ').replace('\n', '\\n')
    return (
        '<' + str(priority) + '>1 ' + timestamp + ' ' + safe_host + ' ' +
        safe_app + ' - - - ' + safe_message
    ).encode()


class RemoteSyslog:
    def __init__(self, settings=None, hostname='iotapp', ca_path='', queue_limit=32,
                 status_callback=None):
        self.settings = settings or {}
        self.hostname = str(hostname or 'iotapp')
        self.ca_path = str(ca_path or '')
        self.queue_limit = max(1, min(128, int(queue_limit)))
        self.queue = []
        self.dropped = 0
        self.delivered = 0
        self.failures = 0
        self.consecutive_failures = 0
        self.last_error = ''
        self.status_callback = status_callback
        self.tls_session = TLSSessionHandle()

    @property
    def enabled(self):
        return self.settings.get('enabled') is True

    @property
    def audit_enabled(self):
        return self.settings.get('audit_enabled', self.enabled) is True

    @property
    def active(self):
        return self.enabled or self.audit_enabled

    def enqueue(self, timestamp, message, severity='INFO', audit=False):
        if not (self.audit_enabled if audit else self.enabled):
            return False
        if len(self.queue) >= self.queue_limit:
            self.queue.pop(0)
            self.dropped += 1
        self.queue.append(rfc5424_message(
            timestamp, self.hostname, 'IoT-MD-Audit' if audit else 'IoT-MD',
            message, severity
        ))
        return True

    def status(self):
        return {
            'active': self.active,
            'transport': str(self.settings.get('transport', 'udp')),
            'host': str(self.settings.get('host', '')),
            'port': int(self.settings.get(
                'port', 6514 if self.settings.get('transport') == 'tls' else 514
            )),
            'queued': len(self.queue),
            'delivered': self.delivered,
            'dropped': self.dropped,
            'failures': self.failures,
            'consecutive_failures': self.consecutive_failures,
            'last_error': self.last_error,
        }

    def overview_status(self):
        if not self.active:
            return 'Disabled'
        return 'Error' if self.last_error else 'Online'

    def _notify(self, severity, message):
        if not self.status_callback:
            return
        try:
            self.status_callback(severity, message)
        except Exception:
            pass

    def _delivery_failed(self, exc):
        detail = str(exc) or exc.__class__.__name__
        previous = self.last_error
        self.failures += 1
        self.consecutive_failures += 1
        self.last_error = detail
        # Avoid adding the same retry error to the local device log every five
        # seconds. A changed error is still reported immediately.
        if self.consecutive_failures == 1 or detail != previous:
            self._notify(
                'ERROR', 'Delivery failed - ' + detail + '; retrying in 5 seconds'
            )

    def _delivery_succeeded(self):
        recovered = self.consecutive_failures
        self.delivered += 1
        self.consecutive_failures = 0
        self.last_error = ''
        if recovered:
            self._notify(
                'INFO', 'Delivery recovered after ' + str(recovered) +
                (' failure' if recovered == 1 else ' failures')
            )

    def _tls_context(self):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        if hasattr(context, 'verify_mode') and hasattr(ssl, 'CERT_REQUIRED'):
            context.verify_mode = ssl.CERT_REQUIRED
        try:
            context.load_verify_locations(cafile=self.ca_path)
        except TypeError:
            with open(self.ca_path, 'rb') as stream:
                context.load_verify_locations(cadata=stream.read())
        if hasattr(context, 'check_hostname'):
            context.check_hostname = True
        return context

    async def _send_udp(self, payload):
        host = self.settings.get('host', '')
        port = int(self.settings.get('port', 514))
        address = socket.getaddrinfo(host, port, 0, socket.SOCK_DGRAM)[0][-1]
        connection = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            connection.sendto(payload, address)
        finally:
            connection.close()

    async def _open_tls(self):
        host = self.settings.get('host', '')
        port = int(self.settings.get('port', 6514))
        context = self._tls_context()
        return await open_tls_connection(
            asyncio, host, port, context, host, self.tls_session
        )

    async def run(self):
        tls_reader = None
        tls_writer = None
        while self.active:
            if not self.queue:
                await asyncio.sleep_ms(100) if hasattr(asyncio, 'sleep_ms') else await asyncio.sleep(0.1)
                continue
            payload = self.queue[0]
            try:
                if self.settings.get('transport', 'udp') == 'tls':
                    if tls_writer is None:
                        tls_reader, tls_writer = await self._open_tls()
                    # RFC 6587 octet counting avoids ambiguous newline framing.
                    frame = str(len(payload)).encode() + b' ' + payload
                    tls_writer.write(frame)
                    await tls_writer.drain()
                else:
                    await self._send_udp(payload)
                self.queue.pop(0)
                self._delivery_succeeded()
            except Exception as exc:
                self._delivery_failed(exc)
                if tls_writer is not None:
                    await http_support.close_writer(tls_writer)
                tls_reader = None
                tls_writer = None
                await asyncio.sleep(5)
        if tls_writer is not None:
            await http_support.close_writer(tls_writer)
