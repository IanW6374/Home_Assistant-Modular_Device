"""Bounded MQTT publishing and transport-neutral module command dispatch."""

try:
    import uasyncio as asyncio
except ImportError:
    import asyncio

try:
    import uos as os
except ImportError:
    import os

try:
    import ubinascii as binascii
except ImportError:
    import binascii

try:
    import time
except ImportError:
    time = None


def _ticks_ms():
    if time and hasattr(time, 'ticks_ms'):
        return time.ticks_ms()
    return int(time.time() * 1000) if time else 0


def _ticks_diff(end, start):
    if time and hasattr(time, 'ticks_diff'):
        return time.ticks_diff(end, start)
    return end - start


class BoundedPublishQueue:
    """Keep critical MQTT messages FIFO and coalesce ordinary state by topic."""

    def __init__(self, state_limit=64, critical_limit=24):
        self.state_limit = max(1, int(state_limit))
        self.critical_limit = max(1, int(critical_limit))
        self._critical = []
        self._state_order = []
        self._state = {}
        self._stats = {
            'enqueued': 0,
            'dequeued': 0,
            'coalesced': 0,
            'dropped': 0,
            'critical_dropped': 0,
            'high_watermark': 0,
        }

    @staticmethod
    def is_critical(message):
        if message.get('critical') is not None:
            return bool(message.get('critical'))
        topic = str(message.get('data', {}).get('topic', ''))
        return (
            bool(message.get('retain')) or
            topic.endswith('/availability') or
            topic.endswith('/response') or
            topic.endswith('/config')
        )

    def put(self, data, qos=0, log_only=False, retain=False, critical=None):
        item = {
            'data': data,
            'qos': int(qos),
            'log_only': bool(log_only),
            'retain': bool(retain),
            'critical': critical,
        }
        self._stats['enqueued'] += 1
        if self.is_critical(item):
            if len(self._critical) >= self.critical_limit:
                # Preserve newer availability/responses; the discarded item is
                # explicitly counted and exposed through runtime health.
                self._critical.pop(0)
                self._stats['dropped'] += 1
                self._stats['critical_dropped'] += 1
            self._critical.append(item)
        else:
            key = (
                str(data.get('topic', '')), int(qos), bool(retain)
            )
            if key in self._state:
                self._state[key] = item
                self._stats['coalesced'] += 1
            else:
                if len(self._state_order) >= self.state_limit:
                    oldest = self._state_order.pop(0)
                    self._state.pop(oldest, None)
                    self._stats['dropped'] += 1
                self._state_order.append(key)
                self._state[key] = item
        self._stats['high_watermark'] = max(
            self._stats['high_watermark'], self.depth()
        )
        return True

    def get_nowait(self):
        if self._critical:
            item = self._critical.pop(0)
        elif self._state_order:
            key = self._state_order.pop(0)
            item = self._state.pop(key)
        else:
            return None
        self._stats['dequeued'] += 1
        return item

    def depth(self):
        return len(self._critical) + len(self._state_order)

    def stats(self):
        result = dict(self._stats)
        result['depth'] = self.depth()
        result['state_depth'] = len(self._state_order)
        result['critical_depth'] = len(self._critical)
        return result


class ModuleBroker:
    """Bounded shared command queue used by MQTT and the HTTPS API."""

    def __init__(self, devices_getter, queue_limit=16, operation_limit=32,
                 command_timeout_ms=15000):
        self.devices_getter = devices_getter
        self.queue_limit = max(1, int(queue_limit))
        self.operation_limit = max(self.queue_limit, int(operation_limit))
        self.command_timeout_ms = max(1000, int(command_timeout_ms))
        self._queue = []
        self._operations = {}
        self._operation_order = []
        self._listeners = []
        self._sequence = 0
        self._running = False

    def add_listener(self, listener):
        self._listeners.append(listener)

    def _new_id(self):
        self._sequence += 1
        try:
            return binascii.hexlify(os.urandom(8)).decode()
        except Exception:
            return str(_ticks_ms()) + '-' + str(self._sequence)

    def _device(self, uuid):
        return next(
            (item for item in self.devices_getter()
             if str(item.get('uuid')) == str(uuid) and item.get('driver')),
            None
        )

    def submit(self, uuid, payload, source='api', identity=''):
        if not isinstance(payload, dict):
            raise ValueError('module command payload must be an object')
        device = self._device(uuid)
        if device is None:
            raise KeyError('module not found: ' + str(uuid))
        if len(self._queue) >= self.queue_limit:
            raise RuntimeError('module command queue is full')
        request_id = str(payload.get('request_id') or self._new_id())[:64]
        payload = dict(payload)
        payload['request_id'] = request_id
        operation = {
            'id': request_id,
            'module': str(uuid),
            'source': str(source),
            'identity': str(identity)[:96],
            'status': 'queued',
            'submitted_ms': _ticks_ms(),
            'completed_ms': None,
            'payload': payload,
            'result': None,
            'error': '',
        }
        self._operations[request_id] = operation
        self._operation_order.append(request_id)
        while len(self._operation_order) > self.operation_limit:
            old = self._operation_order.pop(0)
            if self._operations.get(old, {}).get('status') not in ('queued', 'processing'):
                self._operations.pop(old, None)
        self._queue.append(operation)
        driver = device['driver']
        if hasattr(driver, 'set_response_callback'):
            driver.set_response_callback(
                lambda response, module_uuid=str(uuid):
                self.complete_external(module_uuid, response)
            )
        return self.operation(request_id)

    def operation(self, operation_id):
        value = self._operations.get(str(operation_id))
        if value is None:
            return None
        result = dict(value)
        result.pop('payload', None)
        return result

    def state(self, uuid):
        device = self._device(uuid)
        if device is None:
            raise KeyError('module not found: ' + str(uuid))
        return device['driver'].get_state_payload()

    def diagnostics(self, uuid):
        device = self._device(uuid)
        if device is None:
            raise KeyError('module not found: ' + str(uuid))
        driver = device['driver']
        return driver.diagnostics_payload() if hasattr(driver, 'diagnostics_payload') else {}

    def catalog(self):
        result = []
        for device in self.devices_getter():
            if str(device.get('uuid')) == '0000' or not device.get('driver'):
                continue
            driver = device['driver']
            config = getattr(driver, 'device', {}) or {}
            result.append({
                'uuid': str(device.get('uuid')),
                'name': str(config.get('name', device.get('uuid', ''))),
                'type': config.get('type', {}),
                'capabilities': ['state', 'diagnostics', 'read', 'write'],
            })
        return result

    def _notify(self, operation):
        snapshot = self.operation(operation['id'])
        for listener in tuple(self._listeners):
            try:
                listener(snapshot)
            except Exception:
                pass

    def complete_external(self, uuid, response):
        request_id = ''
        if isinstance(response, dict):
            request_id = str(response.get('request_id') or '')
        operation = self._operations.get(request_id)
        if not operation or operation.get('module') != str(uuid):
            return False
        operation['status'] = 'complete' if response.get('ok', True) else 'failed'
        operation['result'] = response
        operation['error'] = '' if response.get('ok', True) else str(response.get('error', 'command failed'))
        operation['completed_ms'] = _ticks_ms()
        self._notify(operation)
        return True

    async def run(self):
        self._running = True
        while self._running:
            if not self._queue:
                await asyncio.sleep_ms(20) if hasattr(asyncio, 'sleep_ms') else await asyncio.sleep(0.02)
                continue
            operation = self._queue.pop(0)
            device = self._device(operation['module'])
            if device is None:
                operation['status'] = 'failed'
                operation['error'] = 'module is no longer available'
                operation['completed_ms'] = _ticks_ms()
                self._notify(operation)
                continue
            operation['status'] = 'processing'
            started = _ticks_ms()
            try:
                driver = device['driver']
                result = driver.set(operation['payload'])
                if not (isinstance(result, dict) and result.get('defer_publish')):
                    operation['result'] = {
                        'driver_result': result,
                        'state': driver.get_state_payload(),
                    }
                    operation['status'] = 'complete'
                    operation['completed_ms'] = _ticks_ms()
                    self._notify(operation)
                    continue
                while operation['status'] == 'processing':
                    if _ticks_diff(_ticks_ms(), started) >= self.command_timeout_ms:
                        operation['status'] = 'failed'
                        operation['error'] = 'module command timed out'
                        operation['completed_ms'] = _ticks_ms()
                        self._notify(operation)
                        break
                    await asyncio.sleep_ms(20) if hasattr(asyncio, 'sleep_ms') else await asyncio.sleep(0.02)
            except Exception as exc:
                operation['status'] = 'failed'
                operation['error'] = str(exc)
                operation['completed_ms'] = _ticks_ms()
                self._notify(operation)

    def stop(self):
        self._running = False

    def stats(self):
        return {
            'queue_depth': len(self._queue),
            'queue_limit': self.queue_limit,
            'operations_retained': len(self._operations),
        }
