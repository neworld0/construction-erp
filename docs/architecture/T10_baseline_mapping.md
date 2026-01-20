# T10 Baseline Onboarding Mapping

## Scope
Baseline onboarding reuses existing T0~T9 models wherever possible. Missing baseline structures are listed as 신규 모델 후보.

## Reuse Models (existing)
- Project: apps/projects/models.py -> Project
- Assignment/RBAC: apps/core/rbac/models.py -> ProjectAssignment, UserProfile, Role
- Cost Item (master): apps/cost/models.py -> CostItem (CostItemCategory)
- Cost Actual: apps/cost/models.py -> CostActual, CostActualLine
- WBS/Progress: apps/schedule/models.py -> SchedulePlan, ScheduleTask, DailyProgress
- Contract/Change: apps/contracts/models.py -> ContractChange, ContractSnapshot
- Revenue: apps/cost/models.py -> RevenueRecognition
- Approval: apps/core/models.py -> ApprovalRequest
- Audit: apps/audit/models.py -> AuditLog
- Evidence: apps/evidence/models.py -> Evidence, EvidenceFile, EvidencePolicy
- Risk: apps/risk/models.py -> RiskRule, RiskEvent, RiskFinding
- Field Report: apps/reports/models.py -> FieldReport, FieldReportFile

## Missing / New Model Candidates (baseline)
- ProjectContract (Project 1:1 contract baseline)
- WBSItem (tree-based WBS with weight, dates)
- BudgetItem (planned cost baseline)

## Field/Model Extensions (if needed)
- Project: no required extension for T10; use existing code/name/client_name/dates.
- ContractSnapshot: ensure baseline version exists (v1) for revenue recognition.
- ScheduleTask: weight_percent is used as WBS weight; parent/child is missing -> WBSItem needed.
- CostItem: present as master list; baseline budget needs separate BudgetItem.

## Ticket Mapping (T2/T5/T6/T8/T9)
- T2 (Projects/RBAC):
  - Project, ProjectAssignment, UserProfile, Role
- T5 (Cost/Revenue):
  - CostItem, CostActual, CostActualLine, RevenueRecognition, ContractSnapshot
- T6 (Schedule/Progress):
  - SchedulePlan, ScheduleTask, DailyProgress, PlanChangeRequest
- T8 (Audit/Security):
  - ApprovalRequest, AuditLog, Evidence/EvidenceFile, RBAC permissions
- T9 (Risk):
  - RiskRule, RiskEvent, RiskFinding

## T10-1 ~ T10-6: Minimal Models/Fields Needed
1) T10-1 Project Baseline
   - Project (code, name, client_name, start_date, end_date, status)
   - ProjectAssignment (user, project, is_active)

2) T10-2 Contract Baseline
   - ContractSnapshot (project, version_no, base_contract_amount, start_date/end_date, is_active)
   - ContractChange (optional, for change workflow)
   - 신규: ProjectContract (project, contract_amount, contract_start_date, contract_end_date, contract_file, status)

3) T10-3 WBS Baseline
   - SchedulePlan (project, version_no, is_active)
   - ScheduleTask (plan, name, weight_percent, start/end dates)
   - 신규: WBSItem (project, name, parent, weight, sort_order, plan_start_date, plan_end_date)

4) T10-4 Budget Baseline
   - CostItem (category, name, unit)
   - 신규: BudgetItem (project, category, name, planned_amount, notes)

5) T10-5 Field Onboarding (Reports/Evidence)
   - FieldReport (project, report_date, title, content, status, created_by)
   - FieldReportFile (report, file, original_name)
   - Evidence (object_type/object_id, title, status)

6) T10-6 Governance (Approval/Audit/Risk)
   - ApprovalRequest (object_type/object_id, status, submitted_by/at)
   - AuditLog (actor, action, object_type/object_id, project)
   - RiskFinding (project, rule, severity, status)

## Notes
- WBS weight and budget baseline are not present today; they should be introduced as new models if T10 requires full baseline onboarding.
- Evidence/CostActual remain separate: baseline contract/WBS/budget must not reference Evidence or CostActual directly. 
