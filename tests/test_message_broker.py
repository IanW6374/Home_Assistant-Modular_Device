import asyncio
import unittest

from message_broker import BoundedPublishQueue
from message_broker import ModuleBroker


class FakeDriver:
    def __init__(self, deferred=False):
        self.value = 0
        self.deferred = deferred
        self.callback = None
        self.device = {
            'name': 'Example', 'uuid': '0001',
            'type': {'class': 'sensor', 'subclass': 'test'}
        }

    def set_response_callback(self, callback):
        self.callback = callback

    def set(self, payload):
        if self.deferred:
            asyncio.get_running_loop().call_soon(
                self.callback,
                {'ok': True, 'request_id': payload['request_id'], 'value': 42}
            )
            return {'defer_publish': True}
        self.value = payload.get('value', self.value)

    def get_state_payload(self):
        return {'value': self.value}

    def diagnostics_payload(self):
        return {'last_ok': True}


class PublishQueueTests(unittest.TestCase):
    def test_coalesces_latest_state_by_topic(self):
        queue = BoundedPublishQueue(state_limit=2)
        queue.put({'topic': 'a/state', 'payload': 1})
        queue.put({'topic': 'a/state', 'payload': 2})

        item = queue.get_nowait()
        self.assertEqual(item['data']['payload'], 2)
        self.assertEqual(queue.stats()['coalesced'], 1)

    def test_critical_messages_are_fifo_and_not_coalesced(self):
        queue = BoundedPublishQueue()
        queue.put({'topic': 'a/state', 'payload': 1})
        queue.put({'topic': 'a/response', 'payload': 2})

        self.assertEqual(queue.get_nowait()['data']['payload'], 2)
        self.assertEqual(queue.get_nowait()['data']['payload'], 1)

    def test_bounds_state_queue_and_counts_drops(self):
        queue = BoundedPublishQueue(state_limit=1)
        queue.put({'topic': 'a/state', 'payload': 1})
        queue.put({'topic': 'b/state', 'payload': 2})

        self.assertEqual(queue.stats()['dropped'], 1)
        self.assertEqual(queue.get_nowait()['data']['topic'], 'b/state')


class ModuleBrokerTests(unittest.IsolatedAsyncioTestCase):
    async def test_executes_synchronous_command(self):
        driver = FakeDriver()
        broker = ModuleBroker(
            lambda: [{'uuid': '0001', 'driver': driver}],
            command_timeout_ms=1000
        )
        submitted = broker.submit('0001', {'value': 7})
        task = asyncio.create_task(broker.run())
        try:
            for _ in range(20):
                await asyncio.sleep(0.01)
                operation = broker.operation(submitted['id'])
                if operation['status'] == 'complete':
                    break
            self.assertEqual(operation['result']['state'], {'value': 7})
        finally:
            broker.stop()
            await asyncio.wait_for(task, 1)

    async def test_completes_deferred_command_from_driver_response(self):
        driver = FakeDriver(deferred=True)
        broker = ModuleBroker(
            lambda: [{'uuid': '0001', 'driver': driver}],
            command_timeout_ms=1000
        )
        submitted = broker.submit('0001', {'operation': 'read'})
        task = asyncio.create_task(broker.run())
        try:
            for _ in range(20):
                await asyncio.sleep(0.01)
                operation = broker.operation(submitted['id'])
                if operation['status'] == 'complete':
                    break
            self.assertEqual(operation['result']['value'], 42)
        finally:
            broker.stop()
            await asyncio.wait_for(task, 1)


if __name__ == '__main__':
    unittest.main()
