# DEMO 3 Sites E2E

## 1) Project Summary
- P1: `ASAN-조경1 공원 리모델링`
  - Contract: `3,000,000,000`
  - Period: `2026-02-01 ~ 2026-05-31`
  - Budget lines: `10~20` seeded (current seed target: `20`)
- P2: `ASAN-토목1 우수관 정비`
  - Contract: `2,000,000,000`
  - Period: `2026-02-01 ~ 2026-04-30`
  - Budget lines: `10~20` seeded (current seed target: `20`)
- P3: `ASAN-건축1 관리동 증축`
  - Contract: `800,000,000`
  - Period: `2026-02-01 ~ 2026-03-31`
  - Budget lines: `10~20` seeded (current seed target: `20`)

## 2) FIELD Flow
- Progress
  - Mixed statuses: `draft/submitted/approved`
  - Includes `rejected -> resubmit` case
  - Most entries have `1~3` attachments
  - Includes R1: `submitted` progress with `0` attachments
- Report
  - Includes one day with `2` reports
  - Includes `rejected -> attachment replace -> resubmit` (same report row updated)
- CostActual
  - Includes multiple entries in one day
  - Includes evidence-attached and no-attachment submitted case
  - Includes R2: `submitted` cost with `0` attachments
- Timesheet
  - `6~10` workdays seeded with mixed states
  - Includes `rejected -> resubmit` case
  - Includes R4: month-end nearby `submitted` left pending

## 3) HQ Inbox Process
- URL: `/app/hq/inbox/`
- Pending queue shaped to keep meaningful counts by type:
  - progress/report/cost/timesheet each `3~5` submitted pending target

## 4) CEO Approval Detail URL
- CEO inbox: `/app/ceo/inbox/`
- CEO adjustments list: `/app/ceo/adjustments/`
- Adjustment detail: `/app/ceo/adjustments/<adjustment_id>/`

## 5) Monthly Close Steps
1. Create/ensure closing period for `2026-02`.
2. Execute close (`OPEN -> CLOSED`) at month end.
3. Verify close guard blocks new write in closed month (`CLOSE-2`).
4. Route post-close changes through Adjustment only.

## 6) Adjustment Flow
- Case A: P1 cost missing (equipment rental)
- Case B: P2 labor/payroll correction
- Flow: `create -> submit -> CEO approve`
- KPI reflection check: approved adjustment totals query includes both project deltas

## 7) Risk Cases
- R5: Attempt draft/write in closed month
  - Expected: blocked by month close guard
  - Fallback UX hint: redirect to `/app/hq/adjustments/`
- R6: Transfer exists but no IssueToWork for that transfer item
  - Expected: remaining stock visible on site warehouse stock view/data

## 8) Data Integrity Checklist
- submit lock: `submitted/approved` attachments are read-only
- reject editable: `rejected` attachments editable
- close block: closed month blocks write path
- adjustment only: closed-month correction by Adjustment flow
- attachment policy: ATT-1 (`draft/rejected` editable, `submitted/approved` locked)
