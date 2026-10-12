FROM debian:trixie-slim@sha256:a29215f6a35e51e22adffa17f89e9d2ef06214e64a2bad10d765c46aea49f11f
RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends chromium xvfb x11vnc openbox x11-xserver-utils tini ca-certificates fonts-liberation python3 && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 browser
COPY start.sh /usr/local/bin/titan-browser
COPY files.py /usr/local/bin/titan-session-files.py
RUN chmod 755 /usr/local/bin/titan-browser
USER 1000:1000
ENV HOME=/home/browser DISPLAY=:0
EXPOSE 5900
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/titan-browser"]
