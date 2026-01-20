CEO KPI demo
============

Seed
----
```
DEMO_ENABLE=true python manage.py seed_demo_3sites
```

Check
-----
- Dashboard: `http://127.0.0.1:8000/app/ceo/`
- KPI detail: `http://127.0.0.1:8000/app/ceo/projects/<id>/kpi/`

Toggles
-------
- `include_submitted=1`: include SUBMITTED data
- `baseline_only=1`: only baseline-ready projects (default)
