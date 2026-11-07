"""Separately startable secured operational API; requires explicit OPERATIONAL_DB and OPERATIONAL_ADMIN_CREDENTIAL."""
import os
import ipaddress
from backend.operational_api import create_app

host=os.environ.get('OPERATIONAL_HOST','127.0.0.1')
try:
    if not ipaddress.ip_address(host).is_loopback:
        raise RuntimeError('OPERATIONAL_HOST must be a loopback address')
except ValueError as exc:
    raise RuntimeError('OPERATIONAL_HOST must be a loopback IP address') from exc

app=create_app()

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app,host=host,port=int(os.environ.get('OPERATIONAL_PORT','8765')))
