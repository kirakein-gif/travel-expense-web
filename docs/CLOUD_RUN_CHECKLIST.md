# Cloud Run 배포 전 체크리스트

## 완료
- FastAPI 웹 UI
- 카카오 주소 검색 / 길찾기 모듈
- 주소 및 외부 경로 캐시 구조
- 충남 관내 고정거리표 우선 구조
- 내포 별도 목적지 코드 `NAEPO`
- OPINET API 유가 조회
- OPINET API ↔ 웹 가격 대조 검증
- 검증된 날짜·시군구·유종 가격 Firestore 영구 캐시
- OPINET 시도 코드 / 시군구 코드표 공유 캐시
- OPINET 날짜 + 시도 + 유종 웹 가격표 1회 조회 후 검증 재사용
- OPINET 결과화면 PNG 캡처
- PDF 산출내역 즉시 생성(서버 장기보관 없음)
- Playwright/Chromium 및 한글 PDF 폰트 Docker 설정
- Cloud Build 배포 시 `CACHE_BACKEND=firestore` 자동 설정

## Cloud Run 운영 확인
1. Google Cloud 프로젝트/결제계정 확인
2. Firestore 데이터베이스가 생성되어 있는지 확인
3. Cloud Run 실행 서비스 계정에 Firestore 읽기/쓰기 권한 확인
4. Secret Manager의 `KAKAO_REST_API_KEY`, `OPINET_API_KEY` 연결 확인
5. 최초 과거 유가 조회 후 Firestore `travel_cache` 컬렉션에 `opinet_validated_price_v1__...` 문서가 생기는지 확인
6. 같은 날짜·같은 시군구·같은 유종을 다시 조회했을 때 화면 출처에 `검증 캐시 · 캐시`가 표시되는지 확인
7. 같은 날짜·같은 시도·같은 유종의 다른 시군구 조회 시 웹 가격표 캐시가 재사용되는지 확인
8. 실제 카카오 주소/거리 테스트
9. Cloud Run 동시성/메모리 조정
10. 예산 알림 설정

## OPINET 캐시 정책
- 당일 유가는 OPINET 일평균 자료가 아직 없으므로 자동조회/영구캐시하지 않음
- 과거 일평균 유가는 API와 웹 가격이 일치한 경우에만 영구 저장
- 기존 `opinet_api_price` 원시 캐시는 신뢰하지 않고 새 `opinet_validated_price_v1` 캐시만 재사용
- 웹 검증 가격표는 날짜 + 시도 + 유종 단위로 영구 재사용
- Firestore 장애 시 서비스 중단 대신 인스턴스 메모리 캐시로 폴백

## 런칭 전 별도 확정
- 충청남도교육청 공식 관내 고정거리표 값 입력
- `내포`의 공식 고정거리 기준점 최종 승인
- 내포 출장의 유가 적용 시군구 기준 확정
- 인증/SSO 방식
- 개인정보 및 PDF 보관정책
