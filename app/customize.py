"""customize/ 폴더 읽기. 요청마다 파일을 다시 읽으므로 재시작 없이 반영됨."""
import json
import re
from pathlib import Path

import yaml

VAR_PATTERN = re.compile(r"\{(\w+)\}")


class CustomizeError(Exception):
    """customize 파일이 없거나 형식이 틀림."""


class Customize:
    def __init__(self, root: Path):
        self.root = Path(root)

    def _read(self, relative: str) -> str:
        path = self.root / relative
        if not path.is_file():
            raise CustomizeError(f"{path.as_posix()} 파일이 없습니다.")
        return path.read_text(encoding="utf-8-sig")

    def domain(self) -> dict:
        try:
            data = yaml.safe_load(self._read("domain.yaml")) or {}
        except yaml.YAMLError as error:
            raise CustomizeError(f"domain.yaml 형식 오류: {error}") from None
        if not isinstance(data, dict):
            raise CustomizeError("domain.yaml 최상위는 key: value 형식이어야 합니다.")
        return data

    def prompt(self, name: str, **values) -> str:
        """prompts/{name}.md 를 읽고 {변수}를 채움. 모르는 {변수}는 그대로 둠."""
        text = self._read(f"prompts/{name}.md")
        text = re.sub(r"<!--.*?-->\s*", "", text, flags=re.S)  # 메모용 주석은 모델에 안 보냄

        def fill(match):
            key = match.group(1)
            return str(values[key]) if key in values else match.group(0)

        return VAR_PATTERN.sub(fill, text).strip()

    def schema(self, name: str) -> dict:
        try:
            return json.loads(self._read(f"schemas/{name}.json"))
        except json.JSONDecodeError as error:
            raise CustomizeError(f"schemas/{name}.json 형식 오류: {error}") from None

    # ---------- domain.yaml 조회 도우미 ----------

    def find(self, section: str, item_id: str | None) -> dict:
        """domain.yaml의 목록(relations 등)에서 id로 항목 찾기. 없으면 입력값을 label로 사용."""
        if not item_id:
            return {}
        for item in self.domain().get(section) or []:
            if item.get("id") == item_id:
                return item
        return {"id": item_id, "label": item_id}  # 목록에 없는 자유 입력 허용
