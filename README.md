# ⚡ TechDeal KR — 테크 특가 모음

한국 주요 쇼핑몰(쿠팡, 11번가, G마켓, 네이버쇼핑 등)의 IT 기기 특가를 한눈에 모아보는 서비스입니다.

🌐 **라이브**: `https://<your-username>.github.io/<repo-name>/`

---

## 주요 기능

- **실시간 특가 목록**: 할인율·절약금액·가격순 정렬
- **카테고리 필터**: 스마트폰, 노트북, 이어폰, 게이밍, 카메라 등 9개 카테고리
- **할인율/가격 필터**: 원하는 조건만 추출
- **타이머**: 특가 마감까지 남은 시간 표시
- **제휴 링크**: 쿠팡 파트너스 등 수익화 지원
- **특가 알림**: 이메일 구독 기능 (연동 필요)

---

## 빠른 시작 (GitHub Pages 배포)

### 1. 저장소 Fork / Clone
```bash
git clone https://github.com/<your-username>/techdealkr.git
cd techdealkr
```

### 2. GitHub Pages 활성화
- 저장소 → Settings → Pages
- Source: **GitHub Actions** 선택
- `main` 브랜치에 푸시하면 자동 배포

### 3. 딜 데이터 수정
`data/deals.json` 파일을 직접 수정하거나 스크래핑 스크립트를 연동하세요.

---

## 프로젝트 구조

```
techdeal-kr/
├── index.html              # 메인 페이지
├── css/
│   └── style.css           # 스타일시트
├── js/
│   └── app.js              # 메인 앱 로직
├── data/
│   └── deals.json          # 특가 데이터 (JSON)
└── .github/
    └── workflows/
        └── deploy.yml      # GitHub Actions 자동 배포
```

---

## 딜 데이터 구조 (`data/deals.json`)

```json
{
  "id": 1,
  "name": "상품명",
  "category": "smartphone",
  "image": "이미지 URL",
  "originalPrice": 799000,
  "salePrice": 569000,
  "store": "쿠팡",
  "affiliateUrl": "https://쿠팡파트너스링크",
  "expiresAt": "2026-06-01T23:59:00",
  "tags": ["핫딜", "역대최저"],
  "rating": 4.5,
  "reviewCount": 2341,
  "inStock": true,
  "freeShipping": true
}
```

**카테고리 목록**: `smartphone` · `laptop` · `tablet` · `audio` · `monitor` · `camera` · `gaming` · `wearable` · `accessory`

**태그 목록**: `핫딜` · `역대최저` · `타임딜` · `카드할인` · `패키지`

---

## 수익화 (제휴마케팅)

### 쿠팡 파트너스
1. [파트너스 가입](https://partners.coupang.com)
2. 상품 링크 생성 → `affiliateUrl` 필드에 삽입
3. 구매 발생 시 **1~3% 수수료** 자동 적립

### 네이버 쇼핑 파트너
1. [스마트스토어 파트너센터](https://partner.naver.com) 가입
2. 상품 링크에 파트너 코드 추가

### Google AdSense
`index.html`의 `<head>` 또는 적절한 위치에 AdSense 코드 삽입

---

## 자동 데이터 업데이트 (선택)

`scripts/scrape_deals.py` (별도 구현 필요):
- Coupang Product API, 11st Open API 연동
- GitHub Actions 스케줄: 하루 3회 자동 실행 (오전 9시, 오후 3시, 9시)

API 키는 GitHub Secrets에 저장:
- `COUPANG_ACCESS_KEY`
- `COUPANG_SECRET_KEY`

---

## 서버 운영비용

| 항목 | 비용 |
|---|---|
| GitHub Pages 호스팅 | 무료 |
| GitHub Actions (CI/CD) | 무료 (월 2,000분) |
| 도메인 (.kr) | 연 ~15,000원 |
| **초기 총비용** | **연 15,000원** |

---

## 라이선스

MIT License — 자유롭게 사용, 수정, 배포 가능합니다.

---

> 본 서비스는 쿠팡 파트너스 등 제휴 마케팅 프로그램에 참여합니다. 링크를 통한 구매 시 소정의 수수료가 지급될 수 있습니다.
