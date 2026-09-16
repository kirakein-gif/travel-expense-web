# 여비정산 자동화 (travel-expense-web)

GitHub + Cloud Run 기반 여비정산 웹앱 MVP입니다.

## 1차 목표
- 카카오 주소 검색 및 자동차 이동거리 산출
- OPINET 과거 특정일 + 시군구 + 유종 자동조회
- OPINET 공식화면 캡처
- 자동차운임 자동계산
- 증빙자료 PDF 묶음 생성

## 기술 스택
- FastAPI
- HTML/CSS/Vanilla JS
- Kakao Local / Kakao Mobility API
- Playwright + Chromium
- Google Cloud Run
- Firestore
- Cloud Storage
- Secret Manager

## 현재 구현 상태
- [x] FastAPI 웹앱
- [x] 기본 UI
- [x] 카카오 주소 좌표 변환
- [x] 카카오 자동차 거리 조회
- [x] 차량별 공통 계산식
- [x] Playwright 캡처 기본 골격
- [ ] OPINET 실제 selector 연결
- [ ] 유가 캐시(Firestore)
- [ ] 증빙 저장(Cloud Storage)
- [ ] 전기차 급속충전요금 연결
- [ ] 수소차 규정/공식가격 출처 확정
- [ ] PDF 생성

## Cloud Run
Cloud Run은 PORT 환경변수로 전달되는 포트를 사용합니다. Dockerfile은 8080을 기본값으로 사용합니다.

## 보안
API Key를 GitHub에 커밋하지 않습니다. 운영 환경에서는 Secret Manager를 사용합니다.
