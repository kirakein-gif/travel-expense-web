# 딸깍 여비정산서

**Ddalkkak Travel Expense** · 간편 자동화 프로그램군 **딸깍(Ddalkkak)**의 여비정산 웹앱입니다.

복잡한 출장·여비 업무를 몇 번의 클릭으로 쉽게 완성할 수 있도록 거리·유가·여비·증빙·PDF 생성을 한 흐름으로 자동화합니다. GitHub + Cloud Run 기반으로 운영합니다.

## 브랜드
- 한글 브랜드명: **딸깍**
- 영문 브랜드명: **Ddalkkak**
- 프로그램 공식명: **딸깍 여비정산서**
- 영문 제품명: **Ddalkkak Travel Expense**

## 현재 설계 원칙
- 충남 관내 관외출장: **교육지원청 간 공식 고정거리표 우선**
- 충남 밖 출장/고정거리 미등록 예외: **카카오 자동차 길찾기**
- 동일 외부 구간: 거리 캐시로 카카오 호출 최소화
- OPINET: **검증된 날짜 + 시군구 + 유종 가격을 Firestore에 영구 캐시**
- OPINET 캐시 미스: **API 조회 → 같은 날짜·시도·유종 웹 가격표 대조 → 일치한 값만 공유 캐시 저장**
- OPINET 웹 검증표: **날짜 + 시도 + 유종당 1회 조회** 후 같은 시도의 시군구 검증에 재사용
- OPINET 지역코드: 시도 코드와 시군구 코드표도 영구 캐시하여 지역코드 API 호출 최소화
- 전기차: **출장일 기준 무공해차 통합누리집 공공 급속요금 이력 자동 적용**
- 수소차: 지역별 가격 편차를 고려해 **수소단가 직접 입력**
- 내포: 일반 행정구역으로 추론하지 않고 별도 목적지 코드 `NAEPO` 사용
- PDF: 요청 시 즉시 생성하고 서버에 장기 보관하지 않음

## OPINET 300회/일 제한 대응
1. 동일 날짜·시군구·유종의 **검증 캐시를 가장 먼저 조회**합니다.
2. 검증 캐시가 있으면 OPINET API와 브라우저를 모두 호출하지 않습니다.
3. 캐시가 없을 때만 OPINET API를 호출합니다.
4. API 가격을 OPINET 웹페이지의 같은 날짜·지역 가격과 비교합니다.
5. 두 값이 일치한 경우에만 `validated=true`로 Firestore에 영구 저장합니다.
6. API/웹 가격이 다르거나 웹 검증에 실패하면 공유 캐시에 저장하지 않고 오류로 처리합니다.
7. 시도 코드·시군구 코드표와 웹의 시도 전체 가격표도 재사용하여 부가 조회를 줄입니다.

운영 Cloud Run 배포는 `CACHE_BACKEND=firestore`를 자동 설정합니다. Firestore가 일시적으로 사용할 수 없는 경우 서비스 자체가 중단되지 않도록 해당 인스턴스의 메모리 캐시로 안전하게 폴백합니다.

## 내포 기준점
현재 개발 기본값은 `충남 홍성군 홍북읍 선화로 22(충청남도교육청)`입니다.
런칭 전 공식 여비 기준에 맞게 최종 승인/수정할 수 있도록 `data/chungnam_distance_master.json`에 분리했습니다.

## 기술 스택
- FastAPI
- HTML/CSS/Vanilla JS
- Kakao Local / Kakao Mobility API
- Playwright + Chromium
- Google Cloud Run
- Firestore(운영 공유 캐시)
- Cloud Storage(오피넷 공통 증빙)
- Secret Manager

## 현재 구현 상태
- [x] FastAPI 웹앱
- [x] 기본 UI
- [x] 카카오 주소 좌표 변환
- [x] 카카오 자동차 거리 조회
- [x] 주소/거리 캐시
- [x] 충남 교육지원청 기준 거리정책 레이어
- [x] 내포 별도 목적지 코드
- [x] 차량별 공통 계산식
- [x] OPINET API 유가 조회
- [x] OPINET API ↔ 웹 가격 대조 검증
- [x] 검증된 유가 Firestore 영구 캐시
- [x] OPINET 지역코드 Firestore 캐시
- [x] OPINET 날짜·시도·유종 웹 가격표 1회 추출 및 재사용
- [x] OPINET 결과화면 PNG 증빙 캡처
- [x] PDF 산출내역 즉시 생성
- [ ] 충남교육청 공식 고정거리표 실제 값 입력
- [ ] Cloud Storage 증빙 업로드
- [x] 전기차 급속충전요금 이력 연결 및 월 1회 변경 점검
- [x] 수소차 단가 직접입력
- [ ] 인증/SSO (런칭 단계 결정)

## Cloud Run
Cloud Run은 `PORT` 환경변수를 사용합니다. Dockerfile 기본값은 8080입니다.
Playwright/Chromium과 한글 PDF용 Noto CJK 폰트를 함께 설치합니다.

`cloudbuild.yaml`은 배포 시 `CACHE_BACKEND=firestore`를 설정합니다. 실제 공유 캐시를 사용하려면 Google Cloud 프로젝트에 Firestore 데이터베이스가 생성되어 있고 Cloud Run 실행 서비스 계정에 Firestore 읽기/쓰기 권한이 있어야 합니다.

## 보안
API Key를 GitHub에 커밋하지 않습니다. 운영 환경에서는 Secret Manager를 사용합니다.

## 다음 단계
`docs/CLOUD_RUN_CHECKLIST.md` 순서대로 Cloud Run의 Firestore 권한과 실제 API/브라우저 검증 동작을 확인합니다.

## 전기차 기준단가 관리
- 운영 이력: `data/ev_charge_price_history.json`
- 계산 기준: 출장 시작일에 유효한 `active` 단가
- 자동 점검: 매월 1일 GitHub Actions가 무공해차 통합누리집의 기후에너지환경부 급속(50~99kW) 요금을 확인
- 변경 감지 시: 즉시 운영 반영하지 않고 `review_required` 항목을 추가한 검토용 PR 생성
- 누리집 갱신일과 실제 시행일이 다를 수 있으므로 공식 공지의 시행일 확인 후 `effective_from` 및 `status=active` 확정
