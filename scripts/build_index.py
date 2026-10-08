"""사전 1회 실행: 공고 원문 → 구조화(Structured Outputs) → 청크 임베딩 → data/notices*.json

사용 (프로젝트 루트에서):
  python scripts/build_index.py                    # 새 공고만 추가 (.env의 MOCK_MODE에 따라 mock/실제)
  python scripts/build_index.py --only n001 n003   # 지정한 공고만 다시 만들기
  python scripts/build_index.py --force            # 전부 다시 만들기 (실제 모드면 크레딧 사용)

MOCK_MODE=1 → customize/samples/notices/{id}.json + 가짜 임베딩 → data/notices.mock.json
MOCK_MODE=0 → HCX-007 구조화 + 임베딩 v2 → data/notices.json
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings  # noqa: E402
from app.customize import Customize  # noqa: E402
from app.hcx import HCXClient, HCXError  # noqa: E402
from app.services.upload_service import structure_notice  # noqa: E402


async def build_one(hcx: HCXClient, customize: Customize, path: Path) -> dict:
    """공고 원문 1개 → notice dict (chunks·emb 포함)."""
    raw = path.read_text(encoding="utf-8-sig")
    return await structure_notice(hcx, customize, path.stem, raw, mock_sample=f"notices/{path.stem}")


async def main(only: list[str] | None, force: bool):
    """knowledge/notices/*.txt → 인덱스. 이미 만든 공고는 건너뜀(--force면 다시), 1개 끝날 때마다 저장."""
    settings = Settings.from_env()
    hcx = HCXClient(settings)
    customize = Customize(settings.customize_dir)
    out = settings.index_path
    existing = json.loads(out.read_text(encoding="utf-8")) if out.is_file() else []
    by_id = {n["id"]: n for n in existing}

    files = sorted((settings.customize_dir / "knowledge" / "notices").glob("*.txt"))
    if only:
        files = [f for f in files if f.stem in only]
    elif not force:
        files = [f for f in files if f.stem not in by_id]

    print(f"[build_index] mock={settings.mock} -> {out.as_posix()} (새로 만들 공고 {len(files)}개)")
    failed = []
    for f in files:
        try:
            notice = await build_one(hcx, customize, f)
        except HCXError as error:
            # 실패한 공고만 건너뛰고 계속 (이미 만든 결과는 보존)
            print(f"  ! {f.stem} 실패: {error.message}")
            failed.append(f.stem)
            continue
        by_id[notice["id"]] = notice
        save(out, by_id)
        print(f"  - {notice['id']} {notice['title']} (조건 {len(notice['conditions'])}, 청크 {len(notice['chunks'])})")

    save(out, by_id)
    print(f"[build_index] 완료: 총 {len(by_id)}개 공고" + (f", 실패 {failed}" if failed else ""))


def save(out: Path, by_id: dict):
    """id 순서로 인덱스 파일 저장."""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(sorted(by_id.values(), key=lambda n: n["id"]), ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", nargs="*", help="다시 만들 공고 id")
    parser.add_argument("--force", action="store_true", help="이미 있는 공고도 전부 다시 만들기")
    args = parser.parse_args()
    asyncio.run(main(args.only, args.force))
