---
name: ERP Feature / Ticket
about: 건설 ERP MVP 기능 개발 티켓 (T1~T8 공통 양식)
title: "[T?-?] 기능 제목을 여기에 입력"
labels: []
assignees: []
---

## 1. Why (이 기능이 필요한 이유)
- 이 기능이 **어떤 문제를 해결하는지**
- ERP 전체 흐름에서 **어디에 위치하는지**
- 대표/현장/본사 중 **누가 쓰는 기능인지**

---

## 2. Scope (구현 범위)
### 포함
- 
- 
- 

### 제외
- 
- 

---

## 3. User Flow (업무 흐름)
1. 사용자가 무엇을 한다
2. 시스템이 어떻게 반응한다
3. 상태(Status)가 어떻게 바뀐다

---

## 4. Data / Model (데이터 구조)
- 주요 모델:
  - 
- 필수 필드:
  - 
- 관계(FK):
  - 
- 상태값(Status):
  - DRAFT / SUBMITTED / APPROVED / POSTED / CLOSED

---

## 5. Business Rules (업무 규칙)
- 승인 전/후 수정 가능 여부:
- 발생주의 / 현금주의 적용 여부:
- project_id 필수 여부:
- 권한(RBAC) 규칙:

---

## 6. API / Interface (있다면)
- Endpoint:
  - 
- Method:
  - 
- Request / Response 요약:

---

## 7. Permission (권한)
- CEO:
- HQ_MANAGER:
- FIELD_USER:

---

## 8. Done Definition (DoD) – 완료 기준
- [ ] 서버에서 규칙이 강제된다 (UI 차단만 ❌)
- [ ] 승인/상태변경 시 AuditLog 기록
- [ ] 권한 위반 시 403 반환
- [ ] 기존 데이터 무결성 유지
- [ ] 테스트 또는 수용 테스트 통과

---

## 9. Acceptance Test (AT) – 수용 테스트
1. 정상 시나리오:
   - 
2. 예외 시나리오:
   - 
3. 권한 위반 시나리오:
   - 

---

## 10. Notes (비고)
- Codex 프롬프트 번호:
- 관련 Issue:
- 후속 확장 예정:

