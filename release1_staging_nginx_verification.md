# Nginx verification

- nginx -t: NOT_EXECUTED; no Linux staging host or Nginx binary is available.
- proxy_pass: template targets the Gunicorn bind placeholder.
- static: template defines a static alias.
- media: template defines a media policy placeholder; protected-upload policy must be reviewed.
- X-Forwarded-Proto: template forwards the scheme.
- HTTPS/logs/upload timeout: template only; no active site config was inspected.
- Result: HOLD. Run nginx -t and HTTPS healthz through the actual staging proxy.
