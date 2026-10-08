// 기존 프론트엔드에 복사해서 사용하세요. CLOVA_API_KEY는 서버 .env에만 둡니다.
const BASE = "http://localhost:8000";
const TEAM_KEY = ""; // 서버 TEAM_API_KEY를 설정했다면 같은 팀 키 입력

async function readResponse(response) {
  const body = await response.json();
  if (!response.ok) throw new Error(JSON.stringify(body.detail ?? body));
  return body;
}

export async function runTask(task, text, context = "") {
  return readResponse(await fetch(`${BASE}/api/run`, {
    method: "POST",
    headers: {"Content-Type": "application/json", "X-Team-Key": TEAM_KEY},
    body: JSON.stringify({task, text, context}),
  }));
}

export async function analyzeImage(file, question) {
  const form = new FormData();
  form.append("file", file);
  form.append("question", question);
  return readResponse(await fetch(`${BASE}/api/vision`, {
    method: "POST", headers: {"X-Team-Key": TEAM_KEY}, body: form,
  }));
}

export async function addDocument(title, text) {
  return readResponse(await fetch(`${BASE}/api/documents`, {
    method: "POST", headers: {"Content-Type": "application/json", "X-Team-Key": TEAM_KEY},
    body: JSON.stringify({title, text}),
  }));
}

export async function askDocument(question, documentIds = []) {
  return readResponse(await fetch(`${BASE}/api/ask`, {
    method: "POST", headers: {"Content-Type": "application/json", "X-Team-Key": TEAM_KEY},
    body: JSON.stringify({question, document_ids: documentIds}),
  }));
}
