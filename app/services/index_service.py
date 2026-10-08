"""공고 인덱스: data/notices*.json 로드, 임베딩 코사인 검색, 리랭커 호출."""
import json
import logging
from pathlib import Path

import numpy as np

from ..hcx import HCXClient, HCXError

log = logging.getLogger("notice")


class NoticeIndex:
    def __init__(self, hcx: HCXClient, path: Path):
        """path의 notices JSON을 읽어 메모리에 올림. 실행 중에는 재생성하지 않음."""
        self.hcx = hcx
        self.path = Path(path)
        self.notices: list[dict] = []
        self._chunk_owner: list[int] = []      # 청크 i가 속한 공고의 인덱스
        self._chunk_ref: list[dict] = []       # 청크 i 원본 (text, source)
        self._matrix = np.zeros((0, 0), dtype=np.float32)
        self.load()

    # ---------- 로드·조회 ----------

    def load(self):
        """파일에서 공고를 읽고 청크 벡터 행렬을 만듦. 파일이 없으면 빈 인덱스."""
        if not self.path.is_file():
            log.warning("%s 없음: scripts/build_index.py를 먼저 실행하세요.", self.path.as_posix())
            self.notices = []
        else:
            self.notices = json.loads(self.path.read_text(encoding="utf-8"))
        self._rebuild()

    def _rebuild(self):
        """청크 벡터를 정규화한 행렬로 쌓음 (코사인 = 내적)."""
        owners, refs, vectors = [], [], []
        for i, notice in enumerate(self.notices):
            for chunk in notice.get("chunks") or []:
                if chunk.get("emb"):
                    owners.append(i)
                    refs.append(chunk)
                    vectors.append(chunk["emb"])
        self._chunk_owner, self._chunk_ref = owners, refs
        if vectors:
            m = np.asarray(vectors, dtype=np.float32)
            self._matrix = m / np.maximum(np.linalg.norm(m, axis=1, keepdims=True), 1e-12)
        else:
            self._matrix = np.zeros((0, 0), dtype=np.float32)

    def get(self, notice_id: str) -> dict | None:
        """id로 공고 찾기."""
        return next((n for n in self.notices if n["id"] == notice_id), None)

    def add(self, notice: dict, persist: bool = True):
        """공고 1개 추가. persist=True면 파일에도 저장 (/notice/upload 용)."""
        self.notices = [n for n in self.notices if n["id"] != notice["id"]] + [notice]
        self._rebuild()
        if not persist:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.notices, ensure_ascii=False), encoding="utf-8")

    def next_id(self) -> str:
        """다음 공고 id (n006 형식)."""
        nums = [int(n["id"][1:]) for n in self.notices if n["id"][1:].isdigit()]
        return f"n{max(nums, default=0) + 1:03d}"

    # ---------- 검색 ----------

    async def search_chunks(self, feature: str, query: str, k: int = 20,
                            notice_id: str | None = None) -> list[dict]:
        """질의 임베딩 → 청크 코사인 Top k. notice_id를 주면 그 공고 청크만."""
        if self._matrix.size == 0:
            return []
        q = np.asarray((await self.hcx.embed(feature, query)).data, dtype=np.float32)
        if q.shape[0] != self._matrix.shape[1]:
            raise HCXError(500, "질의 벡터와 인덱스 벡터 차원이 다릅니다. 인덱스를 다시 만드세요.")
        sims = self._matrix @ (q / max(float(np.linalg.norm(q)), 1e-12))
        rows = range(len(sims))
        if notice_id:
            rows = [i for i in rows if self.notices[self._chunk_owner[i]]["id"] == notice_id]
        top = sorted(rows, key=lambda i: -sims[i])[:k]
        return [{
            "notice": self.notices[self._chunk_owner[i]],
            "text": self._chunk_ref[i]["text"],
            "source": self._chunk_ref[i].get("source", ""),
            "sim": float(sims[i]),
        } for i in top]

    async def rerank(self, feature: str, query: str, candidates: list[dict], key=lambda c: c["text"]) -> list[dict]:
        """후보에 rerank 점수(0~1 정규화)를 붙여 높은 순으로 정렬.
        리랭커 경로가 아직 없으면(501) 코사인 점수로 대체하고 로그를 남김."""
        if not candidates:
            return []
        try:
            raw = (await self.hcx.rerank(feature, query, [key(c) for c in candidates])).data
        except HCXError as error:
            if error.status_code != 501:
                raise
            log.warning("리랭커 미설정 → 코사인 점수로 대체: %s", error.message)
            raw = [c.get("sim", 0.0) for c in candidates]
        top = max(max(raw), 1e-12)
        for c, s in zip(candidates, raw):
            c["rerank"] = round(max(float(s), 0.0) / top, 4)
        return sorted(candidates, key=lambda c: -c["rerank"])


def group_by_notice(hits: list[dict]) -> list[dict]:
    """청크 검색 결과를 공고 단위로 묶음. sim은 공고 내 최고 청크 점수."""
    groups: dict[str, dict] = {}
    for h in hits:
        nid = h["notice"]["id"]
        g = groups.setdefault(nid, {"notice": h["notice"], "sim": h["sim"], "chunks": []})
        g["sim"] = max(g["sim"], h["sim"])
        g["chunks"].append(h)
    return sorted(groups.values(), key=lambda g: -g["sim"])


def notice_brief(notice: dict) -> str:
    """리랭커에 넘길 공고 요약 문자열."""
    conds = " / ".join(c.get("text", "") for c in notice.get("conditions") or [])
    return f"{notice.get('title', '')}. {' '.join(notice.get('summary') or [])} 자격: {conds}"
