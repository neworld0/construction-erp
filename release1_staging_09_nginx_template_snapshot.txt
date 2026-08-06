# RELEASE-1-FIX staging Nginx reverse proxy configuration

Use this reviewed template only on the staging host. Replace placeholders through the secure deployment process.

```nginx
server {
    listen 443 ssl http2;
    server_name <STAGING_DOMAIN>;
    ssl_certificate <CERTIFICATE_PATH>;
    ssl_certificate_key <CERTIFICATE_KEY_PATH>;
    client_max_body_size 25m;
    access_log <LOG_DIR>/nginx-access.log;
    error_log <LOG_DIR>/nginx-error.log warn;

    location /static/ { alias <STATIC_ROOT>/; }
    location /media/ { alias <MEDIA_ROOT>/; }
    location = /healthz/ { proxy_pass http://<GUNICORN_BIND>; }
    location / {
        proxy_pass http://<GUNICORN_BIND>;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
        proxy_send_timeout 120s;
    }
}
```

Validate `nginx -t`, a HTTPS `/healthz/` request, static/media authorization policy, upload size, forwarded headers, access/error logs, HSTS/CSP policy, `SECURE_SSL_REDIRECT`, and secure session/CSRF cookies. Do not expose private uploaded files through an unrestricted media alias if staging policy requires access control.
