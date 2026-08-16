# Throwaway image for tools/extract_page.py — built on first use by extract.sh.
#
# curl_cffi is the point of it: it fetches with a real Chrome TLS fingerprint,
# which the backend's httpx cannot do, and that alone unblocks the sites that
# reject the server on its handshake rather than its User-Agent.
FROM python:3.13-slim

RUN pip install --no-cache-dir \
        curl_cffi==0.13.0 \
        beautifulsoup4==4.12.3 \
        websocket-client==1.9.0

WORKDIR /tools
