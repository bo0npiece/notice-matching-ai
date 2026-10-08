"""사용자 DB: 프로필 저장, 관심 공고, 서류 체크리스트, user_id로 추천."""
from .conftest import build_client

PROFILE = {"age": 22, "region": "경기", "city": "용인", "school_year": 3, "major": "인공지능", "enrolled": True}


def test_user_profile_flow(client):
    r = client.post("/users", json={})
    assert r.status_code == 201
    uid = r.json()["user_id"]
    assert r.json()["profile"]["age"] is None

    client.post("/profile", json={"text": "용인 사는 22살", "user_id": uid})   # 변환 + 저장
    assert client.get(f"/users/{uid}").json()["profile"]["region"] == "경기"

    client.put(f"/users/{uid}/profile", json={"profile": {**PROFILE, "region": "서울", "city": None, "enrolled": False}})
    ids = [i["id"] for i in client.post("/recommend", json={"user_id": uid}).json()["items"]]
    assert "n004" in ids and "n002" not in ids    # 저장된 서울 프로필로 추천

    body = client.post("/explain", json={"user_id": uid, "notice_id": "n004"}).json()
    assert body["conditions"]


def test_saved_timeline_and_checklist(client):
    uid = client.post("/users", json={"profile": PROFILE}).json()["user_id"]
    for nid in ("n003", "n001", "n002"):
        assert client.post(f"/users/{uid}/saved", json={"notice_id": nid}).status_code == 201
    client.post(f"/users/{uid}/saved", json={"notice_id": "n001"})          # 중복 저장은 무시
    items = client.get(f"/users/{uid}/saved").json()["items"]
    assert [i["notice_id"] for i in items] == ["n001", "n002", "n003"]      # 마감 임박순
    assert client.get(f"/users/{uid}").json()["saved_count"] == 3

    item = client.put(f"/users/{uid}/saved/n001/checklist",
                      json={"checked": ["재학증명서", "없는 서류"]}).json()["item"]
    assert item["checked_count"] == 1 and item["doc_count"] == 4
    assert {d["name"]: d["checked"] for d in item["documents"]}["재학증명서"] is True

    assert client.delete(f"/users/{uid}/saved/n001").json() == {"ok": True}
    assert client.delete(f"/users/{uid}/saved/n001").status_code == 404
    assert len(client.get(f"/users/{uid}/saved").json()["items"]) == 2


def test_user_errors(client):
    assert client.get("/users/nope").status_code == 404
    assert "error" in client.post("/recommend", json={}).json()           # profile도 user_id도 없음
    uid = client.post("/users").json()["user_id"]
    assert client.post(f"/users/{uid}/saved", json={"notice_id": "n999"}).status_code == 404
    assert client.put(f"/users/{uid}/saved/n001/checklist", json={"checked": []}).status_code == 404


def test_users_persist_across_restart(tmp_path):
    uid = build_client(tmp_path).post("/users", json={"profile": PROFILE}).json()["user_id"]
    assert build_client(tmp_path).get(f"/users/{uid}").json()["profile"]["age"] == 22
