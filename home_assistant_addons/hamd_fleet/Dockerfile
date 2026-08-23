ARG BUILD_FROM
FROM ${BUILD_FROM}

RUN apk add --no-cache py3-cryptography py3-sqlite3
COPY rootfs /
RUN chmod a+x /etc/services.d/hamd-fleet/run
