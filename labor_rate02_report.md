# LABOR-RATE-MASTER-02 결과

- HQ 운영 경로: `/app/hq/labor/rates/`
- 단가 우선순위: 프로젝트+근로자(100), 프로젝트+직종(80), 근로자(60), 기본 직종(40)
- FIELD 제출: 적용 단가를 자동 해석하고 `TimesheetLine`에 단가, 기준, 적용일, 해석 시각을 보존합니다.
- 검증: `python manage.py check` 통과, 집중 테스트 12건 통과.

기존 `/app/hq/master/labor/rates/` 경로는 호환 경로로 유지합니다.
