# The flattened amd64 root matches the Docker-Image digest in the signed
# umbrelOS 2.1.0-beta.2 manifest. It includes its kernel, firmware and AI runtime.
FROM ghcr.io/getumbrel/umbrelos@sha256:aad59f5522770566fb343e563142be27299bf4f5d5d97b1f8df9a921e1cffb42
RUN rm -rf /opt/umbreld/ui /opt/umbreld/source
COPY packages/ui/dist /opt/umbreld/ui
COPY packages/umbreld/source /opt/umbreld/source
COPY packages/umbreld/package.json /opt/umbreld/package.json
COPY LICENSE.md /usr/share/doc/titan/LICENSE.md
