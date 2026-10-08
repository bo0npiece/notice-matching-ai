# 공고 비서 백엔드 API

- 기본 주소: `http://localhost:8000` (Swagger: `/docs`)
- 모든 요청·응답은 JSON (`Content-Type: application/json`), 업로드만 `multipart/form-data`
- CORS 전체 허용
- 에러는 항상 `{"error": "메시지"}` + HTTP 상태 코드 (400 잘못된 이미지, 404 없는 공고, 422 요청 형식, 429 크레딧 한도, 502/504 HCX 오류)
- `MOCK_MODE=1`이면 AI를 부르지 않고 고정 예시로 응답 (화면 개발용)

## 화면 흐름

1. 자기소개 입력 → `POST /profile` → 프로필 카드 (사용자가 고칠 수 있게)
2. `POST /recommend` → 추천 카드 목록
3. 카드 클릭 → `POST /explain` → 조건별 ✅❌❓ + 출처
4. 질문 입력 → `POST /ask`
5. 포스터 업로드 → `POST /notice/upload` → 다시 `/recommend` 하면 반영됨
6. 토큰 대시보드 → `GET /usage`

## POST /profile

```json
// 요청
{"text": "용인 사는 22살 AI학과 3학년, 자취 중"}
// 응답 (모르는 값은 null)
{"profile": {"age": 22, "region": "경기", "city": "용인", "school": null, "school_year": 3,
  "major": "인공지능", "enrolled": true, "living_alone": true, "income": null, "gpa": null,
  "interests": ["AI"]}}
```

## POST /recommend

```json
// 요청 (profile은 /profile 응답 그대로 또는 폼에서 직접 구성)
{"profile": {"age": 22, "region": "경기", "city": "용인", "school_year": 3, "major": "인공지능", "enrolled": true},
 "top_k": 5}
// 응답 (score 높은 순, 자격 미달(fail)·마감 지난 공고는 빠짐)
{"query": "경기 용인 거주 22세 인공지능학과 3학년 재학생",
 "items": [{"id": "n002", "title": "[가상] 새봄장학회 경기 지역인재 생활비 장학금", "category": "장학금",
   "score": 0.951, "dday": 38, "benefit": "월 30만원 × 6개월 (총 180만원)",
   "summary": ["경기도 거주 만 19~29세 대학생 대상", "월 30만원씩 6개월 생활비 지원", "11월 15일까지 온라인 접수"],
   "doc_count": 3, "status_count": {"pass": 3, "fail": 0, "unknown": 0, "ai": 1}}]}
```

- `score`: 0~1 적합도
- `dday`: 마감까지 남은 일수 (마감일 없으면 `null`)
- `status_count.ai`: 아직 AI 판단 전인 조건 수 (`/explain`에서 판단됨)

## POST /explain

```json
// 요청
{"profile": {...}, "notice_id": "n003"}
// 응답
{"notice_id": "n003", "title": "[가상] 청년 월세 지원사업", "category": "정책",
 "benefit": "월 최대 20만원 × 12개월", "url": "https://example.com/youth-rent",
 "conditions": [
   {"text": "경기도 거주", "status": "pass", "source": "2항", "by": "rule",
    "reason": "내 거주 지역: 경기 용인 → 조건 '경기도 거주' 충족"},
   {"text": "청년 가구 기준중위소득 60% 이하, 원가구 100% 이하", "status": "unknown", "source": "3항", "by": "ai",
    "reason": "소득 정보가 없어 확인 필요 → 건강보험료 납부확인서로 확인"}],
 "status_count": {"pass": 3, "fail": 0, "unknown": 2, "ai": 0},
 "documents": ["임대차계약서 사본", "월세 이체 내역", "주민등록등본", "가족관계증명서"],
 "deadline": "2026-12-31", "dday": 84}
```

- `status`: `pass` ✅ / `fail` ❌ / `unknown` ❓
- `by`: `rule`(코드로 확실히 판단) / `ai`(공고 원문 근거 AI 판단)
- `source`: 공고 원문 위치 → `GET /notices/{id}`의 `chunks[].source`와 같은 값이라 하이라이트에 사용 가능
- 같은 프로필·공고는 서버가 캐시하므로 다시 눌러도 빠름

## POST /ask

```json
// 요청 (notice_id 생략하면 전체 공고에서 검색)
{"question": "이 장학금이랑 국가장학금 중복 돼?", "notice_id": "n001"}
// 응답
{"answer": "타 기관의 등록금 전액 장학금과는 중복 수혜가 불가하지만, 생활비성 장학금은 중복이 가능합니다. [한빛미래재단 AI 인재 장학금 · 3항]",
 "sources": [{"notice_id": "n001", "title": "[가상] 한빛미래재단 AI 인재 장학금", "source": "3항",
              "text": "3. 우대 사항 및 제한\n - ..."}]}
```

원문에 없는 내용이면 `answer`가 "공고에 명시되지 않았습니다."이고 `sources`는 빈 배열.

## POST /notice/upload

`multipart/form-data`, 필드 이름 `file` (PNG/JPEG/WEBP/BMP, 20MB 이하)

```js
const fd = new FormData();
fd.append("file", input.files[0]);
const res = await fetch(`${API}/notice/upload`, {method: "POST", body: fd});
```

```json
// 응답: notice 스키마 그대로 (임베딩 제외)
{"notice": {"id": "n006", "title": "[가상] 청년 IT 자격증 응시료 지원사업", "org": "디지털청년센터",
  "category": "정책", "summary": ["...", "...", "..."], "benefit": "IT 자격증 응시료 최대 15만원",
  "deadline": "2026-11-10", "url": "https://example.com/it-cert", "documents": ["응시료 결제 영수증", "주민등록초본"],
  "conditions": [{"key": "region", "type": "in", "values": ["경기"], "text": "경기도 거주", "source": "2항", "...": "..."}],
  "chunks": [{"text": "...", "source": "2항"}], "origin": "upload"}}
```

## GET /notices, GET /notices/{id}

```json
// GET /notices
{"items": [{"id": "n001", "title": "...", "category": "장학금", "deadline": "2026-10-31", "dday": 23}]}
// GET /notices/n001 → {"notice": {notice 전체 + "dday"}}
```

## GET /usage?recent=50

```json
{"total_tokens": 1234, "prompt_tokens": 1100, "completion_tokens": 134, "calls": 12, "live_calls": 10, "mock": false,
 "by_call": [{"feature": "explain_judge", "models": ["HCX-007"], "calls": 3, "total_tokens": 900, "...": "..."}],
 "by_model": {"HCX-007": {"calls": 5, "total_tokens": 1100, "...": "..."}},
 "limits": {"max_live_calls": 300, "token_stop_threshold": 200000},
 "logs": [{"ts": "2026-10-08T08:08:08+00:00", "feature": "ask", "kind": "json", "model": "HCX-007",
           "prompt_tokens": 800, "completion_tokens": 60, "total_tokens": 860, "mock": false, "cached": false,
           "status": "ok", "error": null, "latency_ms": 1500}]}
```

## GET /health

`{"ok": true, "mock": true, "mock_reason": "MOCK_MODE=1", "api_key_configured": false, "models": {...}, "index_file": "data/notices.mock.json", "notice_count": 5}`
