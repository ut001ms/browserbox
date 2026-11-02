# browserbox: a Chromium desktop in a box, for the owner (noVNC) and for agents
# (screenshot/click/type API + Chrome DevTools Protocol). Runs as uid 1000 with
# no capabilities, which is all pi3-deploy allows, so Chromium uses --no-sandbox:
# the container is the sandbox.
FROM caddy:2 AS caddy

FROM debian:bookworm-slim
ENV DEBIAN_FRONTEND=noninteractive LANG=C.UTF-8 DISPLAY=:1
RUN apt-get update && apt-get install -y --no-install-recommends \
      chromium xvfb openbox x11vnc novnc python3-websockify xdotool scrot \
      fonts-liberation fonts-dejavu-core fonts-noto-core fonts-noto-color-emoji \
      tzdata ca-certificates curl procps \
    && rm -rf /var/lib/apt/lists/*
COPY --from=caddy /usr/bin/caddy /usr/bin/caddy
COPY rootfs/ /
RUN useradd -m -u 1000 -s /bin/bash sandbox \
    && mkdir -p /home/sandbox/data /home/sandbox/Uploads /home/sandbox/Downloads \
    && touch /home/sandbox/data/.keep \
    && mkdir -p /tmp/.X11-unix && chmod 1777 /tmp/.X11-unix \
    && chown -R sandbox:sandbox /home/sandbox \
    && chmod +x /opt/browserbox/entrypoint.sh
USER 1000
WORKDIR /home/sandbox
EXPOSE 8080
ENTRYPOINT ["/opt/browserbox/entrypoint.sh"]
