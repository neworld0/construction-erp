# LABPAY 1~10 테스트용 샘플 파일 세트

## 대상 프로젝트
- 프로젝트명: 국도46호선 호평IC교(상)등 포장및시설물 보수공사6
- 기준월: 2026-05
- 업체명: (주)아산
- 공제가입번호: 25-02101-0260

## 포함 파일

1. `01_WorkerMaster_등록샘플.xlsx`
   - LABPAY-1 WorkerMaster 등록 검증용입니다.
   - `테스트등록대상=Y`인 4명만 먼저 등록하세요.
   - `최민수`, `정미라`는 처음에는 등록하지 말고 LABPAY-8의 UNMATCHED 처리 검증 때 사용하세요.

2. `02_ERP_노무원장_입력샘플.xlsx`
   - LABPAY-2~4 ERP 노무 원장/신고용 현장 매핑 검증용입니다.
   - 현재 ERP에 엑셀 import가 없다면 화면에서 수동 입력하세요.
   - `actual_project`, `report_project`는 모두 `국도46호선 호평IC교(상)등 포장및시설물 보수공사6`로 입력합니다.

3. `03_CWMA_전자카드_원본업로드_2026-05.xlsx`
   - LABPAY-5 업로드용 핵심 파일입니다.
   - `/app/hq/labor/e-card-imports/`에서 기준월 `2026-05`, 현장 `국도46호선 호평IC교(상)등 포장및시설물 보수공사6`로 업로드하세요.
   - 실제 헤더 `근로년월`, `비대상사유`, `1일~31일`, `신고일수`, `확정일수`, `비고`를 포함합니다.

4. `04_대사처리_확정가이드.xlsx`
   - LABPAY-7~8 대사 결과를 어떻게 처리할지에 대한 기준표입니다.
   - DIFF / ERP_ONLY / CARD_ONLY / UNMATCHED / EXCLUDED 케이스가 섞여 있습니다.

5. `05_확정근로내역_예상결과.xlsx`
   - LABPAY-9 확정 후 생성되어야 할 `LaborConfirmedWorkDay` 예상 결과입니다.
   - 실제 DB 결과와 비교하세요.

6. `06_LABPAY_1-10_통합샘플팩.xlsx`
   - 위 내용을 한 파일에 모은 통합 검증용 파일입니다.

## 권장 검증 흐름

1. 프로젝트 `국도46호선 호평IC교(상)등 포장및시설물 보수공사6`가 존재하는지 확인합니다.
2. WorkerMaster 샘플에서 `테스트등록대상=Y`인 4명만 등록합니다.
3. ERP 노무 원장 샘플을 기준으로 `LaborWorkLedger`를 입력합니다.
4. 전자카드 원본 파일을 업로드합니다.
5. 파싱 후 Raw 6건, Day 186건(6명 × 31일)을 확인합니다.
6. 대사 실행 후 다음 유형이 나오는지 확인합니다.
   - MATCH
   - DIFF
   - ERP_ONLY
   - CARD_ONLY
   - UNMATCHED
7. `04_대사처리_확정가이드.xlsx`를 기준으로 HQ가 처리합니다.
8. 최민수는 WorkerMaster 신규등록 후 매칭하거나, 빠른 검증 시 CARD 기준으로 처리할 수 있습니다.
9. 정미라는 EXCLUDED 처리합니다.
10. 모든 미해결 건을 처리한 뒤 대사 전체 확정합니다.
11. `/app/hq/labor/confirmed-work-days/?batch_id=<batch_id>`에서 확정 근로내역을 확인합니다.
12. 확정 배치 상세 화면에서 `재업로드 엑셀 생성`을 실행합니다.
13. 생성된 파일을 다운로드하여 원본 양식이 유지되고, 1일~31일/신고일수/확정일수/비대상사유/비고가 반영되었는지 확인합니다.

## 예상 대사 케이스

- MATCH: 홍길동 5/1, 김철수 5/1, 박영희 5/3, 이영수 5/7
- DIFF: 홍길동 5/2, 김철수 5/2, 박영희 5/4
- ERP_ONLY: 홍길동 5/3, 이영수 5/9
- CARD_ONLY: 홍길동 5/4·5/10, 김철수 5/5·5/6, 박영희 5/5, 이영수 5/8
- UNMATCHED: 최민수 5/11~5/13, 정미라 5/15

## 한글 깨짐 체크

다음 화면에서 한글이 깨지지 않는지 확인하세요.
- `/app/hq/labor/workers/`
- `/app/hq/labor/work-ledger/`
- `/app/hq/labor/reporting-map/`
- `/app/hq/labor/e-card-imports/`
- `/app/hq/labor/e-card-imports/<batch_id>/`
- `/app/hq/labor/confirmed-work-days/`
