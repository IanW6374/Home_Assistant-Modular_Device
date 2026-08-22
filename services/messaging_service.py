"""Messaging boundary that keeps MQTT transport details out of modules."""


class MessagingService:
    def __init__(self, publisher, discovery_publisher=None, status_getter=None):
        self._publisher = publisher
        self._discovery_publisher = discovery_publisher
        self._status_getter = status_getter

    def publish(self, topic, payload, retain=False, qos=0):
        return self._publisher(topic, payload, retain, qos)

    def publish_discovery(self, topic, payload, retain=True, qos=0):
        if self._discovery_publisher is None:
            return self.publish(topic, payload, retain, qos)
        return self._discovery_publisher(topic, payload, retain, qos)

    def status(self):
        return dict(self._status_getter() or {}) if self._status_getter else {}
