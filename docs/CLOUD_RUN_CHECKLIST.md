# Cloud Run 배포 전 체크리스트

## 오늘까지 완료
- FastAPI 웹 UI
- 카카오 주소 검색 / 길찾기 모듈
- 주소 및 외부 경로 캐시 구조
- 충남 관내 고정거리표 우선 구조
- 내포 별도 목적지 코드 `NAEPO`
- OPINET 날짜 + 시도 + 유종 자동조회
- OPINET 1회 조회 결과의 시군구 전체 가격 재사용 구조
- OPINET 결과화면 PNG 캡처
- PDF 산출내역 즉시 생성(서버 장기보관 없음)
- Playwright/Chromium 및 한글 PDF 폰트 Docker 설정

## 내일 Cloud Run에서 할 일
1. Google Cloud 프로젝트/결제계정 확인
2. Artifact Registry 생성
3. Secret Manager에 `KAKAO_REST_API_KEY` 등록
4. Cloud Run 서비스 배포
5. Firestore 생성 후 `CACHE_BACKEND=firestore` 전환
6. Cloud Storage 버킷 생성 후 OPINET 증빙 보관정책 결정
7. 실제 OPINET 브라우저 자동화 테스트
8. 실제 카카오 주소/거리 테스트
9. Cloud Run 동시성/메모리 조정
10. 예산 알림 설정

## 런칭 전 별도 확정
- 충청남도교육청 공식 관내 고정거리표 값 입력
- `내포`의 공식 고정거리 기준점 최종 승인
- 내포 출장의 유가 적용 시군구 기준 확정
- 전기차 급속충전요금 적용 로직
- 수소차 공식가격 적용 기준
- 인증/SSO 방식
- 개인정보 및 PDF 보관정책
