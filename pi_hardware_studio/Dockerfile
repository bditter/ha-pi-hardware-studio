FROM ghcr.io/home-assistant/aarch64-base-python:3.13-alpine3.22

ARG BUILD_VERSION
LABEL \
    io.hass.version="${BUILD_VERSION}" \
    io.hass.type="app" \
    io.hass.arch="aarch64"

RUN apk add --no-cache util-linux

COPY app /opt/pi-hardware-studio
COPY run.sh /run.sh
RUN chmod 0755 /run.sh

WORKDIR /opt/pi-hardware-studio
CMD ["/run.sh"]
