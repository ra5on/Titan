FROM debian:trixie-20261027@sha256:2dc419c6d7fe3dad0a2f9fd469c34cc90b0f9ba642d8fde837fe3d7d34a0e7f1
RUN apt-get update && apt-get install -y --no-install-recommends chromium xvfb x11vnc socat fonts-liberation tini && rm -rf /var/lib/apt/lists/*
COPY start /usr/local/bin/titan-browser
USER 65534:65534
ENTRYPOINT ["/usr/bin/tini","--","timeout","2h","/usr/local/bin/titan-browser"]
