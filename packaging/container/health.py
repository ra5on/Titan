"""Readiness includes host protocol and the persistent database, without login."""
import json
import os
import sys
import urllib.request
from urllib.parse import urlsplit
sys.path.insert(0, '/usr/lib/titan')
from titan import __version__
from titan.web_access import CONFIG, read_config, origin
address = os.environ.get('TITAN_ORIGIN', 'http://127.0.0.1:5001')
if CONFIG.exists():
    config = read_config(CONFIG)
    address = origin(config['host'], config['settings'])
request = urllib.request.Request('http://127.0.0.1:5001/api/health', headers={'Host': urlsplit(address).netloc})
with urllib.request.urlopen(request, timeout=5) as response:
    value = json.load(response)
if value != {'service': 'Titan', 'version': __version__, 'agent_api': 1, 'state_schema': 1}:
    raise SystemExit('Web/agent readiness mismatch')
