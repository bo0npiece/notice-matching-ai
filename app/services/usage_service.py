"""토큰 사용량 조회 (/usage). 기록 자체는 HCXClient가 모든 호출마다 data/usage_log.jsonl에 남김."""
from ..core import Core


def usage_report(core: Core, recent: int = 50) -> dict:
    """총 토큰, 호출명별 합계, 최근 로그(호출명·모델·토큰·시각)."""
    summary = core.hcx.usage.summary(recent)
    models: dict[str, set] = {}
    for r in core.hcx.usage.records():
        models.setdefault(r["feature"], set()).add(r["model"])
    by_call = [{"feature": name, "models": sorted(models.get(name, ())), **stats}
               for name, stats in summary["by_feature"].items()]
    by_call.sort(key=lambda x: -x["total_tokens"])
    total = summary["total"]
    settings = core.settings
    return {
        "total_tokens": total["total_tokens"],
        "prompt_tokens": total["prompt_tokens"],
        "completion_tokens": total["completion_tokens"],
        "calls": total["calls"],
        "live_calls": total["live_calls"],
        "mock": settings.mock,
        "by_call": by_call,
        "by_model": summary["by_model"],
        "limits": {"max_live_calls": settings.max_live_calls,
                   "token_stop_threshold": settings.token_stop_threshold},
        "logs": [{"ts": r["ts"], "feature": r["feature"], "kind": r["kind"], "model": r["model"],
                  "prompt_tokens": r["prompt_tokens"], "completion_tokens": r["completion_tokens"],
                  "total_tokens": r["total_tokens"], "mock": r["mock"], "cached": r["cached"],
                  "status": r["status"], "error": r["error"], "latency_ms": r["latency_ms"]}
                 for r in summary["recent"]],
    }
