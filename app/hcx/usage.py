"""호출 기록: data/usage_log.jsonl 에 한 줄씩 추가."""
import json
from datetime import datetime, timezone
from pathlib import Path


class UsageLog:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, *, feature: str, kind: str, model: str, mock: bool, cached: bool,
               status: str, usage: dict | None = None, latency_ms: int = 0, error: str | None = None):
        usage = usage if isinstance(usage, dict) else {}
        record = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "feature": feature,          # 기능명 (coach, compose ...)
            "kind": kind,                # chat / json / image / embed
            "model": model,
            "mock": mock,
            "cached": cached,
            "status": status,            # ok / error
            "prompt_tokens": usage.get("promptTokens"),
            "completion_tokens": usage.get("completionTokens"),
            "total_tokens": usage.get("totalTokens"),
            "latency_ms": latency_ms,
            "error": error,
        }
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def records(self) -> list[dict]:
        if not self.path.exists():
            return []
        with self.path.open(encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def summary(self, recent: int = 20) -> dict:
        """기능별·모델별 호출 수와 토큰 합계 (/api/usage 용)."""
        records = self.records()

        def total(rows):
            return {
                "calls": len(rows),
                "live_calls": sum(1 for r in rows if not r["mock"] and not r["cached"]),
                "cached_calls": sum(1 for r in rows if r["cached"]),
                "mock_calls": sum(1 for r in rows if r["mock"]),
                "errors": sum(1 for r in rows if r["status"] != "ok"),
                "prompt_tokens": sum(r["prompt_tokens"] or 0 for r in rows),
                "completion_tokens": sum(r["completion_tokens"] or 0 for r in rows),
                "total_tokens": sum(r["total_tokens"] or 0 for r in rows),
                "avg_latency_ms": round(sum(r["latency_ms"] for r in rows) / len(rows)) if rows else 0,
            }

        def group(key):
            groups: dict[str, list] = {}
            for r in records:
                groups.setdefault(r[key], []).append(r)
            return {name: total(rows) for name, rows in sorted(groups.items())}

        return {
            "total": total(records),
            "by_feature": group("feature"),
            "by_model": group("model"),
            "recent": records[-recent:][::-1],
        }

    def live_totals(self) -> dict:
        """실제 API 호출 횟수(실패 포함)와 누적 토큰. 한도 검사용."""
        live = [r for r in self.records() if not r["mock"] and not r["cached"]]
        return {
            "live_calls": len(live),
            "total_tokens": sum(r["total_tokens"] or 0 for r in live),
        }
