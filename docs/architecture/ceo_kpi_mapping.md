# CEO KPI Mapping (C1-0)

## Scope
Baseline vs Actual KPI mapping for CEO dashboard. This document fixes model/field sources and approval rules before implementation.

## Model/Field Mapping

### Project (apps/projects/models.py)
- Model: `Project`
- Key fields:
  - `id`
  - `code`
  - `name`
  - `status` (`draft|submitted|approved|planned|active|closed`)
  - `start_date`, `end_date`
  - `contract_amount` (legacy, not baseline contract source)

### Contract (apps/projects/models.py)
- Model: `ProjectContract`
- Key fields:
  - `project` (OneToOne)
  - `contract_amount`
  - `contract_file`
  - `contract_start_date`, `contract_end_date`
- Baseline contract source for KPI.

### Budget (apps/projects/models.py)
- Model: `BudgetItem`
- Key fields:
  - `project` (FK)
  - `category` (`MATERIAL|SUBCON|EQUIP|LABOR|OVERHEAD|OTHER`)
  - `planned_amount`
  - `cost_item` (optional FK to `CostItem`)
- Budget baseline = sum of `planned_amount` by project.

### WBS (apps/projects/models.py)
- Model: `WBSItem`
- Key fields:
  - `project` (FK)
  - `name`
  - `weight` (0~100)
  - `plan_start_date`, `plan_end_date`
  - `parent` (nullable)
- Used for schedule baseline; ties to progress via task name mapping (T6).

### Actual Cost (apps/cost/models.py)
- Model: `CostActual`
- Key fields:
  - `project` (FK)
  - `report_date`
  - `status` (`draft|submitted|approved|rejected|closed`)
  - `total_amount`
  - `approved_at`
- Line model: `CostActualLine` (`amount`, `cost_item`, `quantity`, `unit_price`)
- Actual cost KPI uses `CostActual` with approved status.

### Progress (apps/schedule/models.py)
- Model: `DailyProgress`
- Key fields:
  - `project` (FK)
  - `task` (ScheduleTask FK)
  - `report_date`
  - `progress_percent`
  - `status` (`draft|submitted|approved`)
- Progress KPI uses approved status by default.

### Approval (apps/core/models.py)
- Model: `ApprovalRequest`
- Key fields:
  - `object_type`, `object_id`
  - `status` (`draft|submitted|approved|rejected`)
  - `approved_at`
- Used when an object does not have its own status or when approval is externalized.

### Audit (apps/audit/models.py)
- Model: `AuditLog`
- Key fields: `action`, `object_type`, `object_id`, `project`, `created_at`
- Used for baseline submit/approve tracking and KPI audit.

### Field Report (apps/reports/models.py)
- Model: `FieldReport`
- Key fields:
  - `project` (FK)
  - `status` (`DRAFT|SUBMITTED|APPROVED`)
  - `report_date`
- Operational signal only (not part of KPI baseline/actual).

## Baseline vs Actual Definitions

### Baseline
- Baseline project = `Project.status == approved`.
- Contract baseline = `ProjectContract.contract_amount`.
- Budget baseline = sum of `BudgetItem.planned_amount` by project.
- WBS baseline = `WBSItem` list and weights (used for progress alignment).

### Actual
- Actual cost = sum of `CostActual.total_amount` where status is approved/closed.
- Actual progress = `DailyProgress.progress_percent` where status is approved.
- Actual revenue (if needed) = `RevenueRecognition.recognized_revenue` (approved snapshot rules apply elsewhere).

## Approval/Submission Criteria (Policy)

### Default KPI Inclusion
- KPI calculations include **APPROVED only**.
- Optional toggle: `include_submitted=False` (default OFF).
- Submitted items are excluded unless explicitly enabled.

### Domain Rules
- Project baseline:
  - `Project.status == approved` => baseline included.
  - `draft/submitted` => exclude from KPI or show as "미확정".
- Contract:
  - Use `ProjectContract` only when project baseline approved.
- Budget:
  - Use BudgetItem only when project baseline approved.
- WBS:
  - Used for mapping only; must exist for baseline completeness.
- CostActual:
  - Include when `status in (approved, closed)` OR `ApprovalRequest` is approved if external.
- DailyProgress:
  - Include when `status == approved` OR approved via `ApprovalRequest` if external.
- FieldReport:
  - Excluded from KPI totals; only used for ops signals.

## KPI Minimum Inputs
- Baseline: `Project.status`, `ProjectContract.contract_amount`, `BudgetItem.planned_amount`
- Actual: `CostActual.total_amount`, `DailyProgress.progress_percent`
- Optional: `WBSItem.weight` for weighted progress, `RevenueRecognition` for earned value

## Edge Cases / Safe Defaults
- `contract_amount == 0` => margin/ratio computations guard with zero division.
- `budget_total == 0` => variance and CPI/SPI calculations must return 0 or None.
- `no approved baseline` => KPI should show "미확정" bucket.
- `no approved actuals` => show 0, not errors.

## Common Approval Utility Spec (C1-1 target)

### API
- `is_approved(obj) -> bool`
- `is_submitted(obj) -> bool`
- `approved_filter(qs, include_submitted=False)`

### Behavior Rules
- If model has `status` field:
  - Approved when `status` in `["approved", "closed", "APPROVED"]`
  - Submitted when `status` in `["submitted", "SUBMITTED"]`
- If no status:
  - Check `ApprovalRequest` with `object_type/object_id`
  - Approved when `ApprovalRequest.status == approved`
  - Submitted when `ApprovalRequest.status == submitted`

### Model-Specific Mapping
- Project baseline: `Project.status`
- Contract: project baseline status governs inclusion
- BudgetItem: project baseline status governs inclusion
- WBSItem: project baseline status governs inclusion
- CostActual: `CostActual.status` or `ApprovalRequest` fallback
- DailyProgress: `DailyProgress.status` or `ApprovalRequest` fallback
- FieldReport: not part of KPI, only operational visibility

## KPI Engine Interface (C1-1)

### Module
- `apps/ceo/services/kpi_engine.py`

### Functions
- `compute_project_kpi(project, as_of_date=None, include_submitted=False) -> dict`
- `compute_kpis_for_projects(projects_queryset_or_ids, as_of_date=None, include_submitted=False) -> dict[project_id]=kpi`

### Output Schema (per project)
- flags: `baseline_ready`, `excluded_reason`
- baseline: `contract_amount`, `budget_total`, `budget_by_category`, `planned_progress_percent`
- actual: `actual_cost_total`, `actual_cost_by_category`, `actual_progress_percent`
- EV/PV/AC: `EV`, `PV`, `AC`
- indices: `CPI`, `SPI`
- forecasts: `EAC_budget`, `forecast_profit`
- burn/schedule: `budget_burn_rate`, `schedule_progress_ratio`
- governance: `pending_approvals_count`
- risk: `risk_score`, `risk_band`

## RiskScore (0~100)

### Weights (fixed)
- Budget risk: 30
- Schedule risk: 30
- Pending approvals: 20
- Baseline/change risk: 20

### Normalization
- clamp01(x) = min(1, max(0, x))

### Components
- budget_risk = clamp01((burn_rate - 0.8) / 0.2)
  - burn_rate <= 0.8 -> 0
  - burn_rate == 1.0 -> 1
- schedule_risk = clamp01((1 - schedule_ratio) / 0.2)
  - schedule_ratio == 1 -> 0
  - schedule_ratio <= 0.8 -> 1
- pending_risk = clamp01(pending_count / 5)
- baseline_change_risk
  - baseline_ready == False -> 1.0
  - baseline_ready == True and pending change exists -> 0.7
  - otherwise -> 0

### Score/Band
- RiskScore = 30*budget_risk + 30*schedule_risk + 20*pending_risk + 20*baseline_change_risk
- Band:
  - 0~30 GREEN
  - 30~60 YELLOW
  - 60+ RED
