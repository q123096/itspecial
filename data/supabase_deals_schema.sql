-- ══════════════════════════════════════════════════════
--  ITSpecial — Supabase deals 테이블 스키마 (최초 1회 실행)
--  Supabase Dashboard → SQL Editor 에서 실행하세요
-- ══════════════════════════════════════════════════════

-- 1. deals 테이블 생성
CREATE TABLE IF NOT EXISTS deals (
  id              INTEGER PRIMARY KEY,
  name            TEXT NOT NULL,
  category        TEXT DEFAULT 'accessory',
  image           TEXT DEFAULT '',
  added_at        TIMESTAMPTZ DEFAULT NOW(),
  original_price  INTEGER DEFAULT 0,
  sale_price      INTEGER DEFAULT 0,
  price_type      TEXT DEFAULT 'regular',
  store           TEXT DEFAULT '',
  product_url     TEXT DEFAULT '',
  affiliate_url   TEXT DEFAULT '',
  expires_at      TIMESTAMPTZ,
  tags            JSONB DEFAULT '["핫딜"]',
  rating          DECIMAL(3,1) DEFAULT 4.0,
  review_count    INTEGER DEFAULT 0,
  in_stock        BOOLEAN DEFAULT true,
  free_shipping   BOOLEAN DEFAULT false,
  price_history   JSONB DEFAULT '[]',
  pinned          BOOLEAN DEFAULT false,
  created_at      TIMESTAMPTZ DEFAULT NOW(),
  updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- 2. updated_at 자동 갱신 트리거
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS deals_updated_at ON deals;
CREATE TRIGGER deals_updated_at
  BEFORE UPDATE ON deals
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- 3. RLS 활성화
ALTER TABLE deals ENABLE ROW LEVEL SECURITY;

-- 4. 정책: 누구나 읽기 가능
DROP POLICY IF EXISTS "anon_read" ON deals;
CREATE POLICY "anon_read" ON deals
  FOR SELECT TO anon USING (true);

-- 5. 정책: anon 쓰기 허용 (어드민 패널용 — 비밀번호 게이트로 보호됨)
DROP POLICY IF EXISTS "anon_write" ON deals;
CREATE POLICY "anon_write" ON deals
  FOR ALL TO anon
  USING (true)
  WITH CHECK (true);

-- 6. 인덱스
CREATE INDEX IF NOT EXISTS deals_category_idx  ON deals (category);
CREATE INDEX IF NOT EXISTS deals_added_at_idx  ON deals (added_at DESC);
CREATE INDEX IF NOT EXISTS deals_pinned_idx    ON deals (pinned);
CREATE INDEX IF NOT EXISTS deals_expires_at_idx ON deals (expires_at);

-- ──────────────────────────────────────────────────────
-- 완료 확인용 쿼리 (실행 후 테이블이 보이면 성공):
-- SELECT table_name FROM information_schema.tables
-- WHERE table_schema = 'public' AND table_name = 'deals';
-- ──────────────────────────────────────────────────────
