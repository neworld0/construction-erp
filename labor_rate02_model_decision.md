# Model Decision

`LaborRateTable`을 재사용했습니다. `worker` 선택 FK를 추가해 직종별 기본 단가와 근로자별 단가를 함께 관리합니다.

`TimesheetLine`에는 `applied_rate`, `applied_rate_scope`, `applied_rate_effective_from`, `applied_rate_resolved_at`을 추가했습니다. 기존 `rate_type`, `unit_rate`, `amount`가 적용 유형과 금액 스냅샷 역할을 계속 수행하므로 과거 제출 금액은 마스터 변경으로 다시 계산되지 않습니다.
