"""Generate the evidence-based OPS-2 operation manual pack. No DB access."""

from __future__ import annotations

import csv
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def write(name: str, body: str) -> None:
    (ROOT / name).write_text(body.strip() + "\n", encoding="utf-8")


def write_csv(name: str, headers: list[str], rows: list[dict]) -> None:
    with (ROOT / name).open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


write(
    "ops2_erp_operation_manual_master.md",
    """
# 건설 ERP 파일럿 운영 매뉴얼

## 1. 문서 목적
이 문서는 파일럿 운영자가 현재 검증된 기능만 안전하게 사용하도록 돕는 실무 안내서입니다. 실제 운영 전에는 역할별 매뉴얼과 보류 항목을 함께 확인합니다.

## 2. 현재 운영 가능 범위
- **VERIFIED**: CEO KPI 조회, HQ 공사·CBS·WBS·예산 기준선 관리, FIELD 진행률 입력, 마감 후 수정 차단, 감사 이력 기본 흐름.
- **PARTIALLY VERIFIED**: Excel 계약·예산 가져오기와 재업로드 파일 처리. 원본 파일은 보관하고 결과를 검토합니다.
- **NEEDS_SAFE_REAL_FILE**: LABPAY 실제 CWMA 전자카드 파일 운영.
- **POLICY PENDING**: 최종 회계 기준의 매출 인식 정책. 현재 파일럿은 `PROGRESS_BASED_PROVISIONAL`입니다.

## 3. 사용자 역할
- **CEO**: 포트폴리오 KPI, 프로젝트 KPI, 승인 상태를 확인합니다.
- **HQ**: 공사 등록, FIELD 배정, CBS/WBS/예산 기준선, 비용·노무·마감 운영을 담당합니다.
- **FIELD**: 배정된 공사의 WBS 작업을 선택해 진행률을 임시저장하거나 제출합니다.
- **LABPAY/회계/관리자**: 노무 대사, 마감, 개인정보 보호, 장애 대응과 점검을 담당합니다.

## 4. 핵심 용어
- **CBS**: 비용을 분류하는 공사비 코드입니다.
- **WBS**: 공사를 작업 단위로 나눈 기준선입니다. 가중치 합계는 100%여야 합니다.
- **KPI**: 계약·예산·진행률·원가·매출·이익을 보는 핵심 지표입니다.
- **AuditLog**: 누가 언제 어떤 업무를 했는지 남기는 감사 이력입니다.
- **Closing**: 월마감입니다. 마감 뒤 원본 수정은 차단되며 승인된 절차만 사용합니다.

## 5. 전체 업무 흐름
1. HQ가 공사 기본정보, 계약금액, CBS, WBS, 예산 기준선을 등록합니다.
2. HQ가 FIELD 사용자를 공사에 배정하고 WBS 가중치 100%와 예산·계약 대사를 확인합니다.
3. FIELD가 작업별 진행률을 입력합니다.
4. HQ가 승인 원가와 노무 데이터를 검토합니다.
5. CEO가 가중 진행률과 잠정 매출·이익 KPI를 확인합니다.
6. 월마감 후에는 수정 대신 승인된 정정·재개 절차를 사용합니다.

## 6. CEO 운영 흐름
CEO는 `/app/ceo/`에서 활성 공사를 보고 프로젝트 목록과 KPI 상세 화면으로 이동합니다. KPI는 단일 작업 진행률이 아니라 WBS 가중 진행률을 기준으로 해석합니다. 자세한 내용은 `ops2_ceo_dashboard_manual.md`를 사용합니다.

## 7. HQ 운영 흐름
HQ는 공사 등록 후 FIELD 배정, WBS 100%, 예산·계약금액 대사를 순서대로 확인합니다. 잠긴 공사·제출·승인·마감 상태의 수정 규칙을 우회하지 않습니다. 자세한 내용은 `ops2_hq_project_budget_manual.md`를 사용합니다.

## 8. FIELD 운영 흐름
FIELD는 배정된 공사에서 WBS 작업을 선택하고 진행률을 입력합니다. 작업 선택 상자가 비어 있으면 HQ가 WBS 기준선을 먼저 점검해야 합니다. 자세한 내용은 `ops2_field_progress_manual.md`를 사용합니다.

## 9. LABPAY 운영 흐름
노무 담당자는 WorkerMaster, 전자카드 업로드, 대사, 확정근로일, 배부 및 Excel 재업로드 흐름을 사용합니다. 실파일은 아직 **NEEDS_SAFE_REAL_FILE** 상태이므로 개인식별정보가 제거된 안전 파일로 별도 검증 전까지 운영 등록에 사용하지 않습니다.

## 10. 월마감 / 정정 / AuditLog 흐름
마감은 기준 데이터를 고정하는 절차입니다. 마감 이후 진행률·원가·노무 수정이 차단되면 임의 수정하지 말고 HQ/회계 승인 절차를 확인합니다. AuditLog에는 업무 식별자·마스킹 정보만 남기며 주민번호·계좌번호 원문은 남기지 않습니다.

## 11. Excel 업로드 / 다운로드 / 재업로드 흐름
원본 Excel은 별도 보관하고, 업로드 전 시트명·필수 헤더·날짜·숫자 형식을 확인합니다. 오류가 나면 원본을 덮어쓰지 말고 오류 화면과 업로드 시각을 ERP 관리자에게 전달합니다.

## 12. KPI 계산과 대시보드 해석
파일럿 `OPS1B-RERUN-SAMPLE-001`은 계약·예산 571,022,700원, WBS 100%, 가중 진행률 5.625%, 원가 10,000,000원으로 검증됐습니다. 인식매출 32,120,026.88원과 이익 22,120,026.88원은 현재 잠정 정책 기준입니다.

## 13. 개인정보 / 보안 / 권한 원칙
각 사용자는 필요한 화면만 접근합니다. FIELD는 CEO 대시보드에 접근할 수 없습니다. 매뉴얼·오류 보고·AuditLog에는 원문 주민번호, 전화번호, 계좌번호를 적지 않습니다.

## 14. 현재 보류 항목
- LABPAY 실제 전자카드 파일: NEEDS_SAFE_REAL_FILE.
- 최종 회계 매출 인식: POLICY PENDING.
- 백업·복구 훈련과 RELEASE-1 배포 리허설: 운영 전 완료 필요.

## 15. 장애 및 오류 대응
대시보드 500, 권한 우회, 마감 차단 실패, 개인정보 노출은 즉시 ERP 관리자에게 알리고 화면·시각·역할을 기록합니다. 데이터는 임의 삭제 또는 직접 DB 수정하지 않습니다.

## 16. 파일럿 운영 체크리스트
공사 활성 상태, FIELD 배정, WBS 100%, 예산·계약 대사, 진행률 입력, CEO KPI, AuditLog, 마감 차단을 매 운영 주기마다 확인합니다.

## 17. 정식 운영 전 필수 확인사항
실파일 안전 검증, 최종 회계 정책, 백업·복구 드릴, 실제 사용자 교육, 배포 리허설을 완료해야 합니다.

## 18. 부록: OPS Evidence 요약
OPS-0은 조건부 운영 준비, OPS-1A는 파일럿 데이터 팩, OPS-1B/R1은 입력·WBS·예산 기준선, OPS-1C는 CEO KPI 값 대사를 검증했습니다. OPS-1C에서는 KPI 상세 화면 관계명 오류를 수정한 뒤 HTTP 200을 재확인했습니다.
""",
)

write(
    "ops2_ceo_dashboard_manual.md",
    """
# CEO dashboard 운영 매뉴얼

## 목적과 접근
CEO dashboard는 활성 공사의 진행·원가·매출·이익을 빠르게 확인하는 화면입니다. CEO는 `/app/ceo/`에서 대시보드와 프로젝트 목록을 열고 KPI 상세 화면을 확인합니다. **VERIFIED: OPS-1C**.

## 지표 읽는 법
- 계약금액: 승인된 공사 계약 기준 금액입니다.
- 예산 합계: CBS 기준 예산 기준선 합계입니다. 계약금액과 차이가 있으면 HQ에 근거를 요청합니다.
- WBS 가중 진행률: 각 작업의 진행률에 WBS 가중치를 곱한 프로젝트 전체 진행률입니다.
- 원가: 승인 또는 마감된 원가 기준 누적 금액입니다.
- 인식매출: 현재 `PROGRESS_BASED_PROVISIONAL` 정책의 잠정 금액입니다.
- 이익/이익률: 인식매출에서 원가를 차감한 참고 지표입니다.

## 파일럿 예시
`OPS1B-RERUN-SAMPLE-001` / 국도 유지보수 파일럿 공사

| 항목 | 검증값 |
|---|---:|
| 계약금액 | 571,022,700 |
| 예산 합계 | 571,022,700 |
| WBS 합계 | 100% |
| 가중 진행률 | 5.625% |
| 원가 | 10,000,000 |
| 인식매출 | 32,120,026.88 |
| 이익 | 22,120,026.88 |
| 이익률 | 약 68.87% |

## 작업 진행률과 프로젝트 진행률의 차이
포장공사 작업이 12.5%이고 WBS 가중치가 45%이면 프로젝트 기여도는 `45 x 12.5 / 100 = 5.625%`입니다. 작업의 12.5%를 프로젝트 전체 진행률로 읽지 않습니다.

## 잠정 매출 정책
현재 정책은 `PROGRESS_BASED_PROVISIONAL`입니다.
`인식매출 = 계약금액 x 가중 프로젝트 진행률 / 100`
이는 OPS-1C 파일럿 검증용 정책이며, 최종 회계 매출 정책은 **POLICY PENDING**입니다.

## 자주 묻는 질문
**현장 입력값과 진행률이 왜 다른가요?** 작업 입력값은 작업 단위이고 CEO KPI는 WBS 가중치를 적용한 프로젝트 값입니다.

**매출이 왜 변하나요?** 현재 잠정 정책이 가중 진행률을 사용하기 때문입니다.

**이익률이 높거나 낮은 이유는 무엇인가요?** 승인 원가와 잠정 인식매출의 시점 차이일 수 있습니다. 원가 상태와 진행률 원천을 HQ와 확인합니다.

**공사가 보이지 않으면 어떻게 하나요?** 공사 활성 상태와 CEO 화면의 기준일을 확인하고 HQ에 공사 등록 상태를 요청합니다.
""",
)

write(
    "ops2_hq_project_budget_manual.md",
    """
# HQ 공사·CBS·WBS·예산 운영 매뉴얼

## HQ 역할
HQ는 공사 기준선을 만들고 FIELD가 안전하게 입력할 수 있는 상태를 준비합니다. **VERIFIED: OPS-1B-RERUN, OPS-1B-R1**.

## 공사 등록 순서
1. 공사 코드, 공사명, 발주처, 계약금액, 시작·종료일, 활성 상태를 확인합니다.
2. FIELD 사용자를 공사에 배정합니다.
3. CBS를 선택해 예산 기준선을 입력합니다.
4. WBS 작업·가중치·계획일을 등록합니다.
5. 계약금액과 예산 합계, WBS 가중치 합계를 대사합니다.
6. CEO와 FIELD 화면에서 공사 가시성을 확인합니다.

## CBS와 Budget
CBS는 비용 분석 코드이고 Budget은 공사 기준선입니다. 예산 카테고리는 재료비, 하도급, 노무비, 경비를 사용합니다. 장비·간접비 성격의 기존 항목은 예산 기준선에서 경비로 해석합니다.

Budget 합계는 계약금액과 일치하는 것이 원칙입니다. 차이가 있으면 누락·관급자재·잔여 공정·정책 근거를 문서화합니다. 관급자재대는 계약 예산 기준선에 자동 포함하지 않습니다.

## WBS 기준선
WBS 가중치 합계는 반드시 **100%**입니다. 파일럿은 토공 20%, 포장공사 45%, 배수공사 20%, 기타공정 15%로 구성됐습니다. 기타공정은 계약-예산 잔액을 숨기기 위한 항목이 아니라 근거를 가진 잔여 작업 패키지로만 사용합니다.

## FIELD 배정과 확인
FIELD 진행률 입력 전에 반드시 ProjectAssignment와 WBS 기준선을 확인합니다. 작업 선택 상자가 비어 있으면 WBS 기준선 작업이 없거나 공사 배정이 누락됐을 수 있습니다.

## 계약 Snapshot
계약 Snapshot은 계약 기준 금액의 버전을 보관합니다. 계약 변경이나 승인 전후 비교가 필요할 때 기준 버전과 적용 상태를 확인합니다.

## HQ 점검표
- CEO 공사 목록에 공사가 보이는가
- FIELD 사용자가 배정됐는가
- FIELD에 WBS 작업이 보이는가
- WBS 합계가 100%인가
- Budget 합계와 계약금액 차이가 설명되는가
- 마감·제출·승인 상태의 잠금 규칙을 지켰는가

테스트 파일에는 실제 개인정보를 사용하지 않으며, 마감된 월 데이터는 승인된 재개·정정 절차 없이 수정하지 않습니다.
""",
)

write(
    "ops2_field_progress_manual.md",
    """
# FIELD 진행률 입력 매뉴얼

## 사용 대상과 조건
FIELD 사용자는 자신에게 배정된 공사만 입력합니다. 공사와 WBS 기준선이 준비돼 있어야 합니다. **VERIFIED: OPS-1B-RERUN, AUDIT-7, AUDIT-9**.

## 입력 순서
1. `/app/field/?tab=progress&project_id=<공사ID>`에서 공사를 선택합니다.
2. 오늘 진행률 입력에서 작업을 선택합니다.
3. 날짜와 진행률을 확인하고 메모를 작성합니다.
4. 임시저장으로 초안을 보관하거나 제출로 HQ 검토 흐름에 넘깁니다.

## 진행률 의미
포장공사 작업 진행률이 12.5%이고 해당 WBS 가중치가 45%이면 CEO KPI의 프로젝트 기여도는 5.625%입니다. FIELD는 작업의 실제 진척을 입력하며, 가중 계산은 시스템이 수행합니다.

## 자주 발생하는 문제
**공사가 보이지 않음**: HQ의 공사 배정 상태를 확인합니다.

**작업 선택 상자가 비어 있음**: HQ가 WBS 기준선 작업 등록과 기준선 상태를 확인합니다. 날짜가 비어 있거나 오늘 계획일이 아니어도 작업 자체를 숨기면 안 됩니다.

**저장 또는 제출이 차단됨**: 마감 상태, 필수 작업 선택, 입력값 오류를 확인합니다. 마감 뒤에는 임의로 새 행을 만들지 않습니다.

**로그인 화면으로 이동함**: 세션이 만료됐을 수 있습니다. 다시 로그인하고 권한을 확인합니다.

## 현장 메모 원칙
메모에는 공사 상태·지연 사유·확인 필요사항을 씁니다. 주민번호·전화번호·계좌번호 같은 개인정보는 기록하지 않습니다.
""",
)

write(
    "ops2_labpay_ecard_manual.md",
    """
# LABPAY / 전자카드 운영 매뉴얼

## 현재 상태
- fixture 기반 전자카드 흐름: **VERIFIED by AUDIT-6**.
- 실제 CWMA 전자카드 파일: **NEEDS_SAFE_REAL_FILE**.
- 실제 개인정보가 있는 파일은 안전 검증과 승인 전까지 운영 자료로 업로드하지 않습니다.

## 기본 흐름
1. WorkerMaster의 마스킹·식별 기준을 확인합니다.
2. 전자카드 Excel을 업로드하고 헤더 검사를 확인합니다.
3. 원시 행과 일자 행을 검토합니다.
4. ERP 원장과 전자카드를 대사합니다.
5. MATCH, ERP_ONLY, CARD_ONLY, DIFF, UNMATCHED 결과를 검토합니다.
6. 해결된 대사 결과만 확정근로일로 생성합니다.
7. 필요한 경우 CWMA 재업로드 Excel을 생성·다운로드합니다.

## 개인정보 원칙
매뉴얼, AuditLog, 오류 보고에는 원문 주민등록번호·전화번호·계좌번호를 쓰지 않습니다. 예시로만 `900101-1******`, `010-0000-0000`, `BANK-PLACEHOLDER`를 사용합니다.

## 문제 해결
**미매칭 근로자**: WorkerMaster 자동 생성에 의존하지 않습니다. 마스킹된 식별정보와 이름·전화번호 정규화 기준을 확인합니다.

**헤더 불일치**: 원본 파일을 수정하지 말고 필수 헤더와 감지된 헤더를 ERP 관리자에게 전달합니다. `근로년월`과 기존 별칭 호환 여부를 확인합니다.

**생성 Excel이 없음**: 배치 확정 상태, 확정근로일, 생성 이력과 권한을 확인합니다.

**재업로드**: 원본 파일을 덮어쓰지 않습니다. 생성된 별도 파일과 AuditLog를 보관합니다.
""",
)

write(
    "ops2_closing_auditlog_manual.md",
    """
# 월마감·정정·AuditLog 매뉴얼

## 월마감 목적
월마감은 특정 기간의 원가·노무·진행률 기준을 고정하고 보고 수치를 재현 가능하게 만드는 절차입니다.

## 수정 차단
마감된 공사의 FIELD 진행률, 원가, 노무 데이터 수정이 차단되면 정상 동작으로 봅니다. 사용자는 우회 입력이나 직접 DB 수정을 하지 않습니다. 재개·정정 정책은 승인된 운영 절차로만 처리하며, 세부 회계 정책은 **POLICY PENDING**일 수 있습니다.

## AuditLog
AuditLog는 등록·수정·확정·다운로드와 같은 중요 업무의 추적 기록입니다. 검토 시 대상, 사용자 역할, 시각, 결과, 마스킹 여부를 확인합니다.

## 기록하면 안 되는 정보
주민번호 원문, 전화번호 원문, 계좌번호 원문, 인증 비밀값은 AuditLog나 오류 메시지에 기록하지 않습니다. 필요한 경우 마스킹 값과 객체 식별자만 사용합니다.

## 감사 점검표
- 마감 뒤 수정 차단이 적용됐는가
- 승인된 정정 근거가 있는가
- AuditLog가 남았는가
- 개인정보 원문이 없는가
- FIELD 권한으로 HQ/CEO 기능을 실행하지 않았는가

근거: AUDIT-6, AUDIT-9, OPS-1B-RERUN.
""",
)

write(
    "ops2_excel_troubleshooting_manual.md",
    """
# Excel 업로드·다운로드·재업로드 문제 해결

## 대상
계약/예산 import, 전자카드 import, 노무·보고 다운로드, CWMA 재업로드 Excel을 다룹니다. 일부 기관별 실파일은 **PARTIALLY VERIFIED** 또는 **NEEDS_SAFE_REAL_FILE** 상태입니다.

## 업로드 전 확인
1. 원본 Excel을 별도 보관합니다.
2. 시트명, 필수 헤더, 기준월, 날짜 형식, 숫자 셀 형식을 확인합니다.
3. 한글이 깨지지 않는 UTF-8/Excel 파일인지 확인합니다.
4. 중복 업로드 여부와 기존 배치 상태를 확인합니다.

## 대표 증상과 대응
- 필수 열 누락: 감지된 헤더를 확인하고 승인된 템플릿을 사용합니다.
- 시트명 오류: 지원되는 시트명인지 ERP 관리자에게 확인합니다.
- 금액이 문자로 인식됨: 콤마·공백·수식 결과를 확인합니다.
- 날짜 형식 오류: 기준월과 일자 형식을 재확인합니다.
- 생성 파일 없음: 배치 상태·권한·확정 조건을 확인합니다.
- 한글 깨짐: 파일 인코딩과 원본 생성 프로그램을 보존해 관리자에게 전달합니다.
- 기관 양식 미지원: 임의 매핑하지 말고 안전 샘플로 별도 검증합니다.

## 사용자 대응 원칙
운영 데이터를 직접 수정하거나 원본을 덮어쓰지 않습니다. 오류 화면, 업로드 시각, 파일명, 사용 역할을 남기고 ERP 관리자에게 템플릿 검증을 요청합니다.

근거: AUDIT-5, AUDIT-6.
""",
)

write(
    "ops2_admin_runbook.md",
    """
# ERP 관리자 Runbook

## 일상 점검
```powershell
python manage.py check
python manage.py makemigrations --check --dry-run
```
오류가 있으면 배포·데이터 정리 전에 원인을 기록합니다. source scan으로 한글 UTF-8과 개인정보 노출 여부를 확인합니다.

## 데이터 작업 원칙
- 프로젝트 삭제는 반드시 dry-run manifest를 먼저 생성하고 `--apply`를 별도로 실행합니다.
- 로컬/demo DB에서만 정리 도구를 실행합니다.
- 운영 DB 삭제·복구는 백업과 승인 없이 실행하지 않습니다.
- Global CBS, 사용자, 역할, 권한, AuditLog는 프로젝트 정리 대상에 포함하지 않습니다.

## 장애 대응
**Dashboard 500**: URL, 역할, 기준일, 서버 로그를 기록하고 최근 배포·관계명·템플릿 오류를 확인합니다.

**RBAC bypass**: 즉시 접근을 중지하고 역할·ProjectAssignment·라우트 권한을 점검합니다.

**Closing guard failure**: 원본 데이터를 변경하지 말고 마감 상태와 승인된 정정 흐름을 확인합니다.

**raw PII exposure**: 로그·다운로드·화면을 차단하고 보안 담당자에게 알립니다.

**Excel generation failure**: 원본 파일을 보존하고 배치 상태·파일 저장소·권한·AuditLog를 확인합니다.

## rollback 원칙
코드는 승인된 배포 버전으로 rollback할 수 있습니다. 데이터 rollback은 검증된 백업이 있어야 하며, AuditLog는 보존합니다.

## RELEASE-1 준비
RELEASE-1 전에는 백업·복구 드릴, 배포 dry-run, 사용자 교육, LABPAY 안전 실파일 검증, 최종 회계 매출 정책을 완료합니다.
""",
)

write_csv(
    "ops2_role_rbac_quick_reference.csv",
    ["Role", "Primary_Menu", "Can_View", "Can_Create", "Can_Edit", "Cannot_Do", "Key_Rule", "Evidence", "Notes"],
    [
        {"Role": "CEO", "Primary_Menu": "CEO dashboard", "Can_View": "portfolio and project KPI", "Can_Create": "approved workflow only", "Can_Edit": "approval decisions", "Cannot_Do": "FIELD-only daily input", "Key_Rule": "CEO dashboard is CEO role", "Evidence": "OPS-1C", "Notes": "KPI values are provisional revenue policy"},
        {"Role": "HQ", "Primary_Menu": "HQ projects and labor", "Can_View": "project, budget, WBS, labor", "Can_Create": "project baseline and assignment", "Can_Edit": "allowed draft workflow", "Cannot_Do": "bypass closing", "Key_Rule": "assign FIELD before input", "Evidence": "OPS-1B-RERUN", "Notes": "CBS/WBS baseline owner"},
        {"Role": "FIELD", "Primary_Menu": "FIELD progress", "Can_View": "assigned project only", "Can_Create": "daily progress", "Can_Edit": "own allowed input", "Cannot_Do": "CEO dashboard and HQ master", "Key_Rule": "ProjectAssignment required", "Evidence": "AUDIT-7/AUDIT-9", "Notes": "WBS task required"},
        {"Role": "LABPAY 담당자", "Primary_Menu": "HQ labor", "Can_View": "worker and e-card batches", "Can_Create": "authorized labor batches", "Can_Edit": "unconfirmed reconciliation", "Cannot_Do": "expose raw PII", "Key_Rule": "real file NEEDS_SAFE_REAL_FILE", "Evidence": "AUDIT-6", "Notes": "use masking"},
        {"Role": "회계/마감 담당자", "Primary_Menu": "HQ closing", "Can_View": "cost and closing evidence", "Can_Create": "approved closing workflow", "Can_Edit": "approved correction only", "Cannot_Do": "post-close direct mutation", "Key_Rule": "AuditLog preserved", "Evidence": "AUDIT-9", "Notes": "final policy pending"},
        {"Role": "ERP 관리자", "Primary_Menu": "admin runbook", "Can_View": "operational evidence", "Can_Create": "approved maintenance only", "Can_Edit": "configuration under policy", "Cannot_Do": "production deletion without backup", "Key_Rule": "dry-run before apply", "Evidence": "OPS-1B-CLEANUP", "Notes": "RELEASE-1 owner"},
        {"Role": "익명 사용자", "Primary_Menu": "login", "Can_View": "none", "Can_Create": "none", "Can_Edit": "none", "Cannot_Do": "protected routes", "Key_Rule": "redirect to login", "Evidence": "OPS-1C", "Notes": "no KPI exposure"},
    ],
)

write_csv(
    "ops2_error_troubleshooting_matrix.csv",
    ["Error_ID", "User_Role", "Screen_or_Workflow", "Symptom", "Likely_Cause", "User_Action", "Admin_Action", "Severity", "Evidence", "Followup"],
    [
        {"Error_ID": "E-01", "User_Role": "FIELD", "Screen_or_Workflow": "progress", "Symptom": "Project not visible", "Likely_Cause": "missing assignment", "User_Action": "ask HQ", "Admin_Action": "check ProjectAssignment", "Severity": "P1", "Evidence": "AUDIT-7", "Followup": "HQ assignment"},
        {"Error_ID": "E-02", "User_Role": "FIELD", "Screen_or_Workflow": "progress", "Symptom": "WBS dropdown empty", "Likely_Cause": "missing WBS baseline", "User_Action": "do not submit", "Admin_Action": "register baseline WBS", "Severity": "P1", "Evidence": "FIELD-PROGRESS-1", "Followup": "HQ WBS check"},
        {"Error_ID": "E-03", "User_Role": "CEO", "Screen_or_Workflow": "dashboard", "Symptom": "CEO KPI value mismatch", "Likely_Cause": "source timing or policy", "User_Action": "check as-of date", "Admin_Action": "reconcile contract/budget/progress/cost", "Severity": "P0", "Evidence": "OPS-1C", "Followup": "KPI reconciliation"},
        {"Error_ID": "E-04", "User_Role": "CEO/HQ", "Screen_or_Workflow": "dashboard", "Symptom": "Dashboard 500", "Likely_Cause": "application error", "User_Action": "record time and route", "Admin_Action": "inspect logs and recent changes", "Severity": "P0", "Evidence": "OPS-1C", "Followup": "incident runbook"},
        {"Error_ID": "E-05", "User_Role": "HQ/LABPAY", "Screen_or_Workflow": "Excel upload", "Symptom": "Excel upload failed", "Likely_Cause": "header/sheet/date mismatch", "User_Action": "preserve original", "Admin_Action": "verify template", "Severity": "P1", "Evidence": "AUDIT-5", "Followup": "Excel troubleshooting"},
        {"Error_ID": "E-06", "User_Role": "LABPAY", "Screen_or_Workflow": "Excel export", "Symptom": "Generated Excel missing", "Likely_Cause": "batch not confirmed or file issue", "User_Action": "check batch state", "Admin_Action": "check storage and AuditLog", "Severity": "P1", "Evidence": "LABPAY-10", "Followup": "export verification"},
        {"Error_ID": "E-07", "User_Role": "LABPAY", "Screen_or_Workflow": "e-card", "Symptom": "E-card unmatched worker", "Likely_Cause": "identity or name-phone mismatch", "User_Action": "do not auto-create", "Admin_Action": "review WorkerMaster match", "Severity": "P1", "Evidence": "LABPAY-6", "Followup": "masked matching"},
        {"Error_ID": "E-08", "User_Role": "HQ/FIELD", "Screen_or_Workflow": "Closing", "Symptom": "Closing mutation blocked", "Likely_Cause": "month is closed", "User_Action": "use approved correction", "Admin_Action": "review closing policy", "Severity": "P1", "Evidence": "AUDIT-4", "Followup": "closing guard"},
        {"Error_ID": "E-09", "User_Role": "All", "Screen_or_Workflow": "Excel/UI", "Symptom": "Korean text broken", "Likely_Cause": "encoding/source issue", "User_Action": "preserve file", "Admin_Action": "run UTF-8 scan", "Severity": "P1", "Evidence": "AUDIT UTF-8", "Followup": "encoding check"},
        {"Error_ID": "E-10", "User_Role": "All", "Screen_or_Workflow": "protected route", "Symptom": "Permission denied", "Likely_Cause": "role rule", "User_Action": "confirm role", "Admin_Action": "review RBAC", "Severity": "P2", "Evidence": "AUDIT-2", "Followup": "RBAC matrix"},
        {"Error_ID": "E-11", "User_Role": "익명 사용자", "Screen_or_Workflow": "protected route", "Symptom": "Login required", "Likely_Cause": "unauthenticated", "User_Action": "login", "Admin_Action": "none", "Severity": "P2", "Evidence": "OPS-1C", "Followup": "session"},
        {"Error_ID": "E-12", "User_Role": "CEO/HQ", "Screen_or_Workflow": "KPI", "Symptom": "Revenue policy unclear", "Likely_Cause": "final accounting policy pending", "User_Action": "treat as provisional", "Admin_Action": "finalize policy", "Severity": "P1", "Evidence": "OPS-1C", "Followup": "FINANCE-REVENUE-POLICY-1"},
    ],
)

write_csv(
    "ops2_training_checklist.csv",
    ["Training_ID", "Role", "Topic", "Required", "Practice_Task", "Completion_Criteria", "Evidence", "Trainer", "Notes"],
    [
        {"Training_ID": "T-01", "Role": "CEO", "Topic": "CEO dashboard reading", "Required": "YES", "Practice_Task": "read pilot KPI", "Completion_Criteria": "explains 5.625 percent", "Evidence": "OPS-1C", "Trainer": "HQ lead", "Notes": "provisional revenue"},
        {"Training_ID": "T-02", "Role": "HQ", "Topic": "HQ project setup", "Required": "YES", "Practice_Task": "create sanitized project", "Completion_Criteria": "master and assignment checked", "Evidence": "OPS-1B-RERUN", "Trainer": "ERP admin", "Notes": "no real PII"},
        {"Training_ID": "T-03", "Role": "HQ", "Topic": "HQ WBS/Budget setup", "Required": "YES", "Practice_Task": "make WBS 100 percent", "Completion_Criteria": "budget reconciles", "Evidence": "OPS-1B-R1", "Trainer": "HQ lead", "Notes": "CBS baseline"},
        {"Training_ID": "T-04", "Role": "FIELD", "Topic": "FIELD progress input", "Required": "YES", "Practice_Task": "save and submit task progress", "Completion_Criteria": "WBS task selected", "Evidence": "AUDIT-7", "Trainer": "HQ lead", "Notes": "assigned project"},
        {"Training_ID": "T-05", "Role": "LABPAY", "Topic": "LABPAY upload rehearsal", "Required": "YES", "Practice_Task": "fixture e-card reconciliation", "Completion_Criteria": "no raw PII", "Evidence": "AUDIT-6", "Trainer": "LABPAY lead", "Notes": "safe real file pending"},
        {"Training_ID": "T-06", "Role": "회계/마감 담당자", "Topic": "Closing guard", "Required": "YES", "Practice_Task": "confirm blocked mutation", "Completion_Criteria": "uses correction policy", "Evidence": "AUDIT-4", "Trainer": "finance lead", "Notes": "do not bypass"},
        {"Training_ID": "T-07", "Role": "ERP 관리자", "Topic": "AuditLog review", "Required": "YES", "Practice_Task": "review masked audit event", "Completion_Criteria": "no raw PII", "Evidence": "AUDIT-3", "Trainer": "security lead", "Notes": "privacy"},
        {"Training_ID": "T-08", "Role": "All", "Topic": "Excel troubleshooting", "Required": "YES", "Practice_Task": "identify missing header", "Completion_Criteria": "original preserved", "Evidence": "AUDIT-5", "Trainer": "ERP admin", "Notes": "template verification"},
        {"Training_ID": "T-09", "Role": "All", "Topic": "Privacy/PII handling", "Required": "YES", "Practice_Task": "mask sample incident", "Completion_Criteria": "uses placeholders", "Evidence": "AUDIT-3", "Trainer": "security lead", "Notes": "mandatory"},
    ],
)

write_csv(
    "ops2_rollout_readiness_checklist.csv",
    ["Gate_ID", "Area", "Check_Item", "Required_Before_Pilot", "Required_Before_Full_Rollout", "Current_Status", "Evidence", "Owner", "Next_Action"],
    [
        {"Gate_ID": "G-01", "Area": "CEO", "Check_Item": "CEO KPI PASS", "Required_Before_Pilot": "YES", "Required_Before_Full_Rollout": "YES", "Current_Status": "PASS", "Evidence": "OPS-1C", "Owner": "CEO/HQ", "Next_Action": "monitor KPI"},
        {"Gate_ID": "G-02", "Area": "FIELD", "Check_Item": "FIELD progress PASS", "Required_Before_Pilot": "YES", "Required_Before_Full_Rollout": "YES", "Current_Status": "PASS", "Evidence": "OPS-1B-RERUN/AUDIT-7", "Owner": "HQ", "Next_Action": "train users"},
        {"Gate_ID": "G-03", "Area": "Baseline", "Check_Item": "WBS 100% rule", "Required_Before_Pilot": "YES", "Required_Before_Full_Rollout": "YES", "Current_Status": "PASS", "Evidence": "OPS-1B-R1", "Owner": "HQ", "Next_Action": "enforce review"},
        {"Gate_ID": "G-04", "Area": "Baseline", "Check_Item": "budget-contract reconciliation", "Required_Before_Pilot": "YES", "Required_Before_Full_Rollout": "YES", "Current_Status": "PASS", "Evidence": "OPS-1B-R1", "Owner": "HQ", "Next_Action": "review exceptions"},
        {"Gate_ID": "G-05", "Area": "LABPAY", "Check_Item": "LABPAY safe file pending", "Required_Before_Pilot": "NO", "Required_Before_Full_Rollout": "YES", "Current_Status": "NEEDS_SAFE_REAL_FILE", "Evidence": "OPS-1C", "Owner": "LABPAY", "Next_Action": "LABPAY-REAL-1"},
        {"Gate_ID": "G-06", "Area": "Finance", "Check_Item": "final revenue accounting policy pending", "Required_Before_Pilot": "NO", "Required_Before_Full_Rollout": "YES", "Current_Status": "POLICY PENDING", "Evidence": "OPS-1C", "Owner": "Finance", "Next_Action": "FINANCE-REVENUE-POLICY-1"},
        {"Gate_ID": "G-07", "Area": "Operations", "Check_Item": "backup dry-run pending", "Required_Before_Pilot": "NO", "Required_Before_Full_Rollout": "YES", "Current_Status": "PENDING", "Evidence": "OPS-2", "Owner": "ERP admin", "Next_Action": "run restore drill"},
        {"Gate_ID": "G-08", "Area": "Release", "Check_Item": "deployment dry-run pending", "Required_Before_Pilot": "NO", "Required_Before_Full_Rollout": "YES", "Current_Status": "PENDING", "Evidence": "RELEASE-1", "Owner": "ERP admin", "Next_Action": "release rehearsal"},
        {"Gate_ID": "G-09", "Area": "Training", "Check_Item": "user training pending", "Required_Before_Pilot": "NO", "Required_Before_Full_Rollout": "YES", "Current_Status": "PENDING", "Evidence": "OPS-2", "Owner": "HQ lead", "Next_Action": "complete checklist"},
        {"Gate_ID": "G-10", "Area": "Admin", "Check_Item": "admin runbook pending", "Required_Before_Pilot": "NO", "Required_Before_Full_Rollout": "YES", "Current_Status": "READY", "Evidence": "OPS-2", "Owner": "ERP admin", "Next_Action": "review runbook"},
    ],
)

write_csv(
    "ops2_manual_gap_register.csv",
    ["Gap_ID", "Manual_Area", "Gap", "Severity", "P0_P1_P2", "Current_Status", "Workaround", "Required_Before_Pilot", "Required_Before_Full_Rollout", "Followup_Prompt"],
    [
        {"Gap_ID": "GAP-01", "Manual_Area": "LABPAY", "Gap": "LABPAY real e-card file not verified", "Severity": "P1", "P0_P1_P2": "P1", "Current_Status": "NEEDS_SAFE_REAL_FILE", "Workaround": "fixture only", "Required_Before_Pilot": "NO", "Required_Before_Full_Rollout": "YES", "Followup_Prompt": "LABPAY-REAL-1"},
        {"Gap_ID": "GAP-02", "Manual_Area": "Finance", "Gap": "final accounting revenue policy pending", "Severity": "P1", "P0_P1_P2": "P1", "Current_Status": "POLICY PENDING", "Workaround": "PROGRESS_BASED_PROVISIONAL label", "Required_Before_Pilot": "NO", "Required_Before_Full_Rollout": "YES", "Followup_Prompt": "FINANCE-REVENUE-POLICY-1"},
        {"Gap_ID": "GAP-03", "Manual_Area": "Release", "Gap": "RELEASE-1 deployment dry-run pending", "Severity": "P1", "P0_P1_P2": "P1", "Current_Status": "PENDING", "Workaround": "local demo only", "Required_Before_Pilot": "NO", "Required_Before_Full_Rollout": "YES", "Followup_Prompt": "RELEASE-1"},
        {"Gap_ID": "GAP-04", "Manual_Area": "Admin", "Gap": "backup/restore drill pending", "Severity": "P1", "P0_P1_P2": "P1", "Current_Status": "PENDING", "Workaround": "do not perform destructive work", "Required_Before_Pilot": "NO", "Required_Before_Full_Rollout": "YES", "Followup_Prompt": "OPS-BACKUP-1"},
        {"Gap_ID": "GAP-05", "Manual_Area": "Training", "Gap": "real user training pending", "Severity": "P2", "P0_P1_P2": "P2", "Current_Status": "PENDING", "Workaround": "use OPS-2 pack", "Required_Before_Pilot": "NO", "Required_Before_Full_Rollout": "YES", "Followup_Prompt": "OPS-TRAINING-1"},
        {"Gap_ID": "GAP-06", "Manual_Area": "Pilot data", "Gap": "real project data beyond sanitized sample pending", "Severity": "P2", "P0_P1_P2": "P2", "Current_Status": "PENDING", "Workaround": "sanitized pilot", "Required_Before_Pilot": "NO", "Required_Before_Full_Rollout": "YES", "Followup_Prompt": "OPS-REAL-DATA-1"},
    ],
)

write_csv(
    "ops2_manual_evidence_manifest.csv",
    ["Evidence_ID", "Manual", "Section", "Source_Artifact", "Evidence_Type", "Claim_Supported", "Confidence", "Contains_PII", "Notes"],
    [
        {"Evidence_ID": "ME-01", "Manual": "master", "Section": "current scope", "Source_Artifact": "OPS-0/OPS-1A", "Evidence_Type": "report", "Claim_Supported": "conditional readiness", "Confidence": "HIGH", "Contains_PII": "NO", "Notes": "OPS-0 source report missing locally; prompt status used"},
        {"Evidence_ID": "ME-02", "Manual": "CEO", "Section": "KPI", "Source_Artifact": "ops1c_kpi_reconciliation_report.md", "Evidence_Type": "report", "Claim_Supported": "KPI values and routes", "Confidence": "HIGH", "Contains_PII": "NO", "Notes": "value-level reconciliation"},
        {"Evidence_ID": "ME-03", "Manual": "HQ", "Section": "baseline", "Source_Artifact": "ops1b_r1_wbs_revenue_alignment_report.md", "Evidence_Type": "report", "Claim_Supported": "WBS 100 and budget reconciliation", "Confidence": "HIGH", "Contains_PII": "NO", "Notes": "sanitized pilot"},
        {"Evidence_ID": "ME-04", "Manual": "FIELD", "Section": "progress", "Source_Artifact": "ops1b_rerun_input_rehearsal_report.md", "Evidence_Type": "report", "Claim_Supported": "FIELD input path", "Confidence": "HIGH", "Contains_PII": "NO", "Notes": "assignment based"},
        {"Evidence_ID": "ME-05", "Manual": "LABPAY", "Section": "e-card", "Source_Artifact": "AUDIT-6 evidence", "Evidence_Type": "audit", "Claim_Supported": "fixture workflow only", "Confidence": "MEDIUM", "Contains_PII": "NO", "Notes": "real file excluded"},
        {"Evidence_ID": "ME-06", "Manual": "Closing", "Section": "guard", "Source_Artifact": "AUDIT-4/AUDIT-9 evidence", "Evidence_Type": "audit", "Claim_Supported": "post-close protection", "Confidence": "MEDIUM", "Contains_PII": "NO", "Notes": "policy caveat"},
    ],
)

write(
    "ops2_manual_index.md",
    """
# OPS-2 운영 매뉴얼 색인

- `ops2_erp_operation_manual_master.md`: 전체 운영 흐름과 제한 사항
- `ops2_ceo_dashboard_manual.md`: CEO KPI 해석
- `ops2_hq_project_budget_manual.md`: HQ 공사·CBS·WBS·Budget 기준선
- `ops2_field_progress_manual.md`: FIELD 진행률 입력
- `ops2_labpay_ecard_manual.md`: LABPAY 전자카드와 개인정보 원칙
- `ops2_closing_auditlog_manual.md`: 월마감·AuditLog
- `ops2_excel_troubleshooting_manual.md`: Excel 오류 대응
- `ops2_admin_runbook.md`: ERP 관리자 실행 절차
""",
)


def source_scan() -> bool:
    paths = [
        "ops2_erp_operation_manual_master.md", "ops2_ceo_dashboard_manual.md", "ops2_hq_project_budget_manual.md", "ops2_field_progress_manual.md", "ops2_labpay_ecard_manual.md", "ops2_closing_auditlog_manual.md", "ops2_excel_troubleshooting_manual.md", "ops2_admin_runbook.md", "ops2_role_rbac_quick_reference.csv", "ops2_error_troubleshooting_matrix.csv", "ops2_training_checklist.csv", "ops2_rollout_readiness_checklist.csv", "ops2_manual_evidence_manifest.csv", "ops2_manual_gap_register.csv",
    ]
    required = {
        "ops2_erp_operation_manual_master.md": ["문서 목적", "현재 운영 가능 범위", "사용자 역할", "핵심 용어", "CEO", "HQ", "FIELD", "LABPAY", "월마감", "AuditLog", "Excel", "현재 보류 항목", "정식 운영 전 필수 확인사항"],
        "ops2_ceo_dashboard_manual.md": ["CEO dashboard", "OPS1B-RERUN-SAMPLE-001", "571,022,700", "5.625", "32,120,026.88", "22,120,026.88", "PROGRESS_BASED_PROVISIONAL"],
        "ops2_hq_project_budget_manual.md": ["공사 등록", "FIELD 배정", "CBS", "WBS", "Budget", "기타공정", "100%"],
        "ops2_field_progress_manual.md": ["FIELD", "진행률", "임시저장", "제출", "포장공사", "12.5", "5.625"],
        "ops2_labpay_ecard_manual.md": ["LABPAY", "전자카드", "NEEDS_SAFE_REAL_FILE", "900101-1******", "010-0000-0000", "BANK-PLACEHOLDER"],
        "ops2_closing_auditlog_manual.md": ["월마감", "수정 차단", "AuditLog", "개인정보"],
        "ops2_excel_troubleshooting_manual.md": ["Excel", "업로드", "다운로드", "재업로드", "한글"],
        "ops2_admin_runbook.md": ["manage.py check", "makemigrations --check --dry-run", "백업", "rollback", "RELEASE-1"],
        "ops2_role_rbac_quick_reference.csv": ["Role", "CEO", "HQ", "FIELD", "익명 사용자"],
        "ops2_error_troubleshooting_matrix.csv": ["Error_ID", "Dashboard 500", "WBS dropdown empty", "Closing mutation blocked"],
        "ops2_training_checklist.csv": ["Training_ID", "CEO", "HQ", "FIELD", "LABPAY"],
        "ops2_rollout_readiness_checklist.csv": ["Gate_ID", "CEO KPI PASS", "LABPAY safe file pending", "deployment dry-run pending"],
        "ops2_manual_gap_register.csv": ["Gap_ID", "LABPAY", "final accounting revenue policy", "RELEASE-1"],
    }
    bad = ["\ufffd", "??", "蹂댄", "移대", "源", "誘몃", "諛뺢", "沅뚰", "嫄댁"]
    raw_patterns = [re.compile(r"\b\d{6}-[1-4]\d{6}\b"), re.compile(r"\b010-\d{4}-\d{4}\b")]
    allowed = {"010-0000-0000"}
    lines, passed = [], True
    for name in paths:
        text = (ROOT / name).read_text(encoding="utf-8")
        reasons = [f"missing: {token}" for token in required.get(name, []) if token not in text]
        reasons.extend(f"bad token: {token}" for token in bad if token in text)
        for pattern in raw_patterns:
            reasons.extend(f"possible raw PII: {value}" for value in pattern.findall(text) if value not in allowed)
        ok = not reasons
        passed = passed and ok
        lines.extend([f"FILE: {name}", f"FILE_SCAN_PASS: {ok}", *(f"REASON: {reason}" for reason in reasons)])
    lines.append(f"OVERALL_SOURCE_SCAN_PASS: {passed}")
    write("ops2_source_scan.txt", "\n".join(lines))
    return passed


if __name__ == "__main__":
    print(f"OPS2_SOURCE_SCAN_PASS={source_scan()}")
