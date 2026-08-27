T10-1: ProjectContract 모델 + 마이그레이션 + seed 백필  \[구현 완료]

T10-2: BudgetItem 모델 + 마이그레이션 + seed 백필  \[구현 완료]

T10-3: KPI 계산 로직에서 ProjectContract/BudgetItem 우선 참조 (fallback 포함)  \[구현 완료]

T10-4 (강화판): HQ 공사 등록(계약/예산/WBS) + 계약서(Evidence) 필수 + 조경 표준 WBS 템플릿 자동 채움  \[구현 완료]

T10-4b: HQ 공사 등록: 예산(BudgetItem) 조경 표준 템플릿 자동 채움 + CBS 자동완성 재사용  \[구현 완료]

T10-4c: 구현용 Codex 프롬프트(상세)  \[구현 완료]

T10-4d (Budget 입력 ↔ CBS 정책 완전 연동)  \[구현 완료]

T10-5-1: (요청 생성/제출) Codex 프롬프트 — 안전 실행 버전  \[구현 완료]

T10-5-2: (CEO 승인/반려 + baseline v2 생성) Codex 프롬프트 — 안전 실행 버전 \[구현 완료]

T10-5-3: (진행률/계산 로직을 “현재 baseline 버전”으로 전환) Codex 프롬프트 — 안전 실행 버전  \[구현 완료]

T10-5-4: WBS 변경 승인 후 “기준선 변경 배지/이력(언제 v2로 바뀌었는지)” 표시  \[구현 완료]

T10-5-5: WBS 변경이 예산/계약(ChangeOrder)와 함께 움직일 때 “동시 승인 묶음(패키지 승인)”  \[구현 완료]

CLOSE-1: 월 마감(ClosingPeriod) 모델 + 마감 상태 전환(OPEN→CLOSED)  \[구현 완료]

CLOSE-2: 마감 이후 수정 금지(전사 공통 가드)  \[구현 완료]

CLOSE-3: 정정(Adjustment) 워크플로우(마감 후 수정 대신 “정정분” 생성 + CEO 승인)  \[구현 완료]

T10-3-EXTRA: KPI를 “월별/주별 타임라인”으로 내보내는 API(그래프용)  \[구현 완료]

T10-3-UI: CEO 대시보드에서 “데이터 품질 배지(OK/미정/추정)”를 같이 표시하도록 UI 반영  \[구현 완료]

\[INV-1] : 재고 관리를 위한 “창고(Warehouse) + 위치(Location)” 기준 구조 구축  \[구현 완료]

\[INV-1-1] : HQ 창고 생성 UI  \[구현 완료]

\[INV-1-2] : 월 마감 관리 화면(HQ UI) \\\[구현 완료]

\[INV-2] : 재고/구매/현장투입의 기준이 되는 “품목 마스터(ItemMaster)” 구축 \\\[구현 완료]

\[INV-3] : InventoryLedger + Stock 현재고 \\\[구현 완료]

\[INV-4] : (Transfer: 본사↔현장 이동) \\\[구현 완료]

\[INV-5] : (옵션/후속) (IssueToWork: 현장 투입 → CBS/원가 자동 집계) \\\[구현 완료]

\[LAB-1] : LaborRole/직종 + 단가표 \\\[구현 완료]

\[LAB-2] : Timesheet 출역부 입력(현장) + 승인(HQ) \\\[구현 완료]

\[LAB-3] : PayrollAllocation 급여 배부 월 단위 입력(HQ) \\\[구현 완료]

\[LAB-4] : 인건비 실적 집계 → 프로젝트/CBS 연동 + KPI 반영 \\\[구현 완료]

\[CLOSE-4] : 프로젝트 마감(Project Close) + 월 마감과 충돌 규칙 \\\[구현 완료]



\[HQ]

1\. C-1: HQ 리스크 카드 고도화 (자동 분류 + 등급화 + 뱃지 + 정렬) \\\[구현 완료]

2\. A-1: HQ 운영 허브 카드 (To-do + 바로가기 + 최근 승인) — HQ Dashboard \\\[구현 완료]

3\. B-1: HQ 승인 Inbox 고도화 (통합 승인함 + 필터/정렬 + Quick Action + 지연/마감 가드) \\\[구현 완료]



\[FIELD]

\[FAST-CODEX] FIELD 진행률 UX 안전장치 3종 (입력 가드 + 제출 확인 모달 + 상태 뱃지 통일)  \[구현 완료]

\[FAST-CODEX] FIELD 진행률 UX 생산성/통제 3종 (어제 값 복사 + 프로젝트 자동선택/로드 개선 + 날짜 선택 잠금) \\\[구현 완료]

\[FAST-CODEX] FIELD 진행률 UX 2종 (미니 바 시각화 + 오늘 미제출 알림 배너) \\\[구현 완료]







\*\*1. FIELD 모바일 Codex 전용 프롬프트 \\\[진행 중]\*\*



\*\*2. FIELD 모바일 사용자 테스트 시나리오 V\*\*



\*\*3. PC vs 모바일 기능 분리 기준표 V\*\*



\*\*4. PWA(홈 화면 설치) 적용 가이드 V\*\*







\\\[CEO]



1\\. CEO KPI 카드 증감/경과율 표시 Codex 프롬프트  \\\[구현 완료]



2\\. CEO 승인 대기 Quick Action 연결 프롬프트 \\\[구현 완료]



3\\. 리스크 요약 문구 자동 생성 로직  \\\[구현 완료]





\[FAST-CODEX] ATT-0: Attachment 표준(미리보기/링크/멀티업로드/임시저장 유지) 확정 + 한글 깨짐(UTF-8) 상시 점검 체계 구축  \[구현 완료]

\[FAST-CODEX] ATT-1 : 공통 Attachment 컴포넌트 구현 + 편집 가능 정책(DRAFT/REJECTED) 내장 + 한글 깨짐 상시 스캔 포함  \[구현 완료]

\[FAST-CODEX] ATT-2: 진행률(Progress) 화면에 공통 첨부 컴포넌트 적용 (상세=인라인 미리보기+편집정책, 목록=‘사진 첨부됨’ 아이콘) + 한글 깨짐 회귀 체크  \[구현 완료]

\[FAST-CODEX] ATT-3: CEO 승인 상세(/app/ceo/approvals/<id>/) 첨부 패널 적용 + 타입별 동일화 + 한글/버튼 정합  \[구현 완료]

\[FAST-CODEX] ATT-4A (STOP-RULE VERSION): 원가/보고서/출역/HQ ‘상세 화면’ 첨부 UX 통일(attachments\\\_panel)만 수행  \[구현 완료]

\[FAST-CODEX] ATT-4B (STOP-RULE VERSION): 원가/보고서/출역/HQ ‘목록 화면’ 첨부 배지(🖼/📎+개수) 통일 적용 + 최소 성능 보장  \[구현 완료]

\[FAST-CODEX] ATT-4C (STOP-RULE VERSION): “임시저장/반려 상태에서 첨부 수정 시 중복 누적” 버그 제거 (보고서/원가/출역 중 실제 발생 탭 1곳만) + 재제출 플로우 안정화  \[구현 완료]

\[FAST-CODEX] ATT-5: 모바일 멀티업로드 E2E 점검/보완 + CEO “승인 완료 목록” → 객체 상세 이동 + 첨부 인라인 확인 + 한글/폰트 안정화  \[구현 완료]

\[FAST-CODEX] FIELD-APPROVED-LISTS-BE: Field용 Approved된 진행률/보고서/원가 리스트 API/뷰  \[구현 완료]

\[FAST-CODEX] FIELD-APPROVED-LISTS-UI: Field 사용자용 “Approved 진행률/보고서/원가 목록” UI 템플릿 + 필터  \[구현 완료]

\[FAST-CODEX] FIELD-APPROVED-LISTS-DETAIL: 목록에서 상세 이동 + 첨부 인라인 표시 + 한글/UX 정합  \[구현 완료]

\[FAST-CODEX] D3E-1 (Compact)  \[구현 완료]

\[FAST-CODEX] D3E-2 (Compact) \[구현 완료]

\[FAST-CODEX] D3E-3 (Compact) \[구현 완료]

\[FAST-CODEX] D3E-4 (Compact)  \[구현 완료]

[FAST-CODEX] FIELD-APPROVED-ADD-ISSUE-TIMESHEET (Compact) [프롬프트 작성완료]





