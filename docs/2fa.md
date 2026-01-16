# Two-Factor Authentication (2FA)

## Overview
This project uses `django-otp` + `django-two-factor-auth` to enforce TOTP-based 2FA.
Login flow: ID/PW -> OTP -> redirect to `/app/`.

## Install
- Add packages from `requirements.txt`
- Run migrations:
  - `python manage.py migrate`

## URLs
- Login: `/login/`
- 2FA setup & recovery: `/account/`
- Logout: `/logout/` (POST)

## Enforcement Rules
- CEO/HQ: 2FA required
- FIELD: optional by default
- Toggle FIELD requirement with:
  - `DJANGO_FIELD_2FA_REQUIRED=true`

## First Login (Setup)
1) Login with ID/PW.
2) If no OTP device is registered, you will be redirected to:
   - `/account/two_factor/setup/`
3) Scan the QR code in an authenticator app.
4) Confirm OTP.

## Recovery Codes
- Setup page issues recovery codes (one-time use).
- Use them from the OTP step if you lost your device.

## Notes
- API requests without 2FA will return `403` for protected routes.
- The server does not log OTP or secrets.
