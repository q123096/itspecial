# GitHub 셋업 가이드 — itspecial.co.kr

## STEP 2 — 코드 업로드

아래 명령어에서 `<GitHub아이디>` 부분만 바꿔서 PowerShell에 붙여넣기:

```powershell
cd "C:\Users\qaz09\OneDrive\바탕 화면\tech"
git remote add origin https://github.com/<GitHub아이디>/itspecial.git
git branch -M main
git add .
git commit -m "첫 배포"
git push -u origin main
```

## STEP 3 — GitHub Pages 활성화

저장소 페이지 → **Settings** 탭 → 왼쪽 메뉴 **Pages**
- Source: **GitHub Actions** 선택
- Save

## STEP 4 — Custom Domain 설정

같은 Pages 설정 화면에서:
- Custom domain 입력칸에: `itspecial.co.kr`
- **Save** 클릭
- Enforce HTTPS 체크박스 활성화 (DNS 전파 후 자동 활성화됨)

## STEP 5 — API 키 Secrets 등록

저장소 → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

| Secret 이름 | 값 | 발급처 |
|---|---|---|
| COUPANG_ACCESS_KEY | 쿠팡 API 액세스 키 | partners.coupang.com → 오픈API |
| COUPANG_SECRET_KEY | 쿠팡 API 시크릿 키 | 동일 |
| NAVER_CLIENT_ID | 네이버 Client ID | developers.naver.com → 앱 등록 |
| NAVER_CLIENT_SECRET | 네이버 Client Secret | 동일 |
| ST11_API_KEY | 11번가 API 키 (선택) | openapi.11st.co.kr |

## STEP 6 — 가비아 DNS 설정

My가비아 → 도메인 관리 → itspecial.co.kr → DNS 정보 → DNS 관리

**추가할 레코드:**

| 타입 | 호스트 | 값 | TTL |
|---|---|---|---|
| A | @ | 185.199.108.153 | 600 |
| A | @ | 185.199.109.153 | 600 |
| A | @ | 185.199.110.153 | 600 |
| A | @ | 185.199.111.153 | 600 |
| CNAME | www | <GitHub아이디>.github.io | 600 |

저장 후 10~30분 대기 (DNS 전파 시간)

## STEP 7 — 배포 확인

저장소 → **Actions** 탭
- 워크플로우 "딜 자동 발굴 → 파트너스 링크 → 배포" 가 초록색 ✅ 이면 완료
- 빨간색 ❌ 이면 클릭해서 오류 메시지 확인

https://itspecial.co.kr 접속해서 사이트 확인!

## STEP 8 — 네이버 개발자 센터 앱 등록

1. https://developers.naver.com/apps/#/register 접속
2. 애플리케이션 이름: `ITSpecial`
3. 사용 API: **검색** 체크
4. 웹 서비스 URL: `https://itspecial.co.kr`
5. 등록 완료 → Client ID / Client Secret 복사
6. GitHub Secrets에 NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 추가 (STEP 5로 돌아가서)

---

완료 후 동작:
- 매일 오전 9시 / 오후 3시 / 오후 9시 자동 실행
- 쿠팡 + 네이버에서 할인 상품 자동 발굴
- 파트너스 링크 자동 생성
- 사이트 자동 배포
- 비용: itspecial.co.kr 도메인 연 22,000원 외 없음
