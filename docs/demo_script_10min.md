# 10‑Minute Demo Script (Control • Evidence • Risk • Report)

Goal: show that ERP enforces control, evidence, risk, and reporting end‑to‑end.

## 0) Pre‑check (1 min)
- Confirm demo data seeded: `python manage.py seed_initial` and `python manage.py seed_demo_flow`
- Open admin: `/admin/`
- Accounts (examples): ceo / example‑password, hq / example‑password, field1 / example‑password

## 1) FIELD: Daily report & cost input (2 min)
Login as **field1**.
- Go to Daily Report list: `/admin/field/dailyreport/`
- Open the latest report and show lines (CostItem + quantity/unit_price).
- Go to Cost Actual list: `/admin/cost/costactual/` and show related entries (draft/submitted).

## 2) HQ: Approval workflow (2 min)
Login as **hq**.
- Open Approval Requests: `/admin/core/approvalrequest/`
- Pick a submitted request and **approve** (or reject) once.
- Mention that status is synced to the target (CostActual).

## 3) HQ: Contract/Plan change submit → approve (2 min)
Still as **hq**.
- Contract Changes: `/admin/contracts/contractchange/`
  - Open a submitted change and approve it once.
  - Mention snapshot rotation (active snapshot version increments).
- Plan Change Requests: `/admin/schedule/planchangerequest/`
  - Open a submitted request and approve it once.

## 4) Evidence: Upload + protected download (1 min)
Still as **hq** (or user with access).
- Evidence list: `/admin/evidence/evidence/`
- Open a record, upload a file (EvidenceFile).
- Download via API (protected):  
  `/api/evidence-files/<id>/download/`  
  Confirm download succeeds and is access‑controlled.

## 5) Risk: OPEN → ACK (1 min)
Still as **hq**.
- Risk Findings list: `/admin/risk/riskfinding/`
- Open an OPEN finding and acknowledge via API:
  `/api/risk/findings/<id>/ack/`
- Confirm status becomes ACK.

## 6) CEO: Dashboard & cash summary (1 min)
Login as **ceo**.
- Dashboard: `/ceo/dashboard/`
  - Show accrual profit/loss, cash summary (confirmed vs planned), and progress.
- Project detail: `/ceo/projects/<id>/`

## 7) CEO/HQ: CSV export + AuditLog (1 min)
Still as **ceo** or **hq**.
- Download CSV:  
  `/api/ceo/reports/project-summary.csv?as_of_date=YYYY‑MM‑DD`
- Confirm file download.

## 8) AuditLog evidence trail (1 min)
Login as **hq** (or admin).
- Audit Logs: `/admin/audit/auditlog/`
- Filter by action:
  - `APPROVAL_APPROVE`
  - `FILE_DOWNLOAD`
  - `RISK_ACK`
  - `REPORT_EXPORT`
- Show that approval, download, ACK, and report export are all tracked.
