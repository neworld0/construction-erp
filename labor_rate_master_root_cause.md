# Root Cause

FIELD 출역부 제출은 이미 HQ 소유 `LaborRateTable`을 역할·날짜·단가유형·프로젝트 기준으로 조회한다. 그러나 해당 역할에 적용 가능한 단가가 없었다. FIELD에는 단가 관리 권한과 화면이 없으므로 현장 입력 오류가 아니라 마스터 데이터 누락이다.

또한 Django `ValidationError`를 문자열로 변환하며 `['...']` 형태가 화면에 보였다.
