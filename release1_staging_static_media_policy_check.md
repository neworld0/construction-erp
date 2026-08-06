# Static / media / upload policy check

- STATIC_ROOT: local path exists; collectstatic dry-run PASS.
- MEDIA_ROOT: local path exists.
- static: actual Nginx static routing is NOT_EXECUTED without staging host.
- media: no public staging media policy was verified.
- Excel: generated/uploaded Excel requires writable restricted storage and Korean filename smoke on staging.
- media backup policy: pending sensitive-upload retention approval.
- Result: HOLD for staging host policy; production remains blocked until media policy is approved.
