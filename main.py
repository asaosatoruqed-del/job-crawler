import os
import json
import time
from datetime import datetime, timezone, timedelta
from typing import List, Optional
import requests
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field
from google import genai
from google.genai import types

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
JOBS_FILE = "jobs.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

class JobItem(BaseModel):
    title_ja: str = Field(description="日本語での職種名（例: シニアバックエンドエンジニア）")
    remote_type: str = Field(description="リモート区分: 'Full Remote', 'Hybrid', 'On-site' のいずれか")
    salary_range: Optional[str] = Field(description="想定年収や報酬（例: $90,000 - $130,000、または ¥9M - ¥13M。不明なら空文字）")
    currency: str = Field(description="通貨: 'USD', 'JPY', 'EUR', 'その他'")
    tags: List[str] = Field(description="主要スタックや属性タグ（例: ['Go', 'AWS', 'FullRemote', 'USD']）")
    summary_ja: str = Field(description="求職者向けに日本語でまとめた2〜3行の魅力・業務概要")

def load_jobs() -> list:
    if os.path.exists(JOBS_FILE):
        try:
            with open(JOBS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except Exception:
            return []
    return []

def save_jobs(jobs: list):
    try:
        with open(JOBS_FILE, "w", encoding="utf-8") as f:
            json.dump(jobs, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[ERROR] 保存失敗: {e}")

def clean_html(html_text: str) -> str:
    soup = BeautifulSoup(html_text, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines)[:4000]

def fetch_open_remote_candidates() -> List[dict]:
    """会社名不問：オープンAPIから最新求人を一括取得"""
    candidates = []
    
    # Arbeitnow API（認証不要・グローバルリモート求人）
    try:
        print("[FETCH] Arbeitnow API から求人を自動収集...")
        res = requests.get("https://www.arbeitnow.com/api/job-board-api", headers=HEADERS, timeout=10)
        if res.status_code == 200:
            items = res.json().get("data", [])
            for item in items:
                candidates.append({
                    "company": item.get("company_name"),
                    "raw_title": item.get("title"),
                    "raw_desc": clean_html(item.get("description", "")),
                    "apply_url": item.get("url"),
                    "source": "Arbeitnow"
                })
    except Exception as e:
        print(f"[WARN] Arbeitnow 取得失敗: {e}")

    # Remotive API（認証不要・ソフトウェア開発求人）
    try:
        print("[FETCH] Remotive API から求人を自動収集...")
        res = requests.get("https://remotive.com/api/remote-jobs?category=software-dev&limit=15", headers=HEADERS, timeout=10)
        if res.status_code == 200:
            items = res.json().get("jobs", [])
            for item in items:
                candidates.append({
                    "company": item.get("company_name"),
                    "raw_title": item.get("title"),
                    "raw_desc": clean_html(item.get("description", "")),
                    "apply_url": item.get("url"),
                    "source": "Remotive"
                })
    except Exception as e:
        print(f"[WARN] Remotive 取得失敗: {e}")

    return candidates

def parse_with_gemini(company_name: str, title: str, raw_desc: str) -> Optional[JobItem]:
    if not GEMINI_API_KEY or not raw_desc.strip():
        return None

    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        prompt = (
            f"以下は企業「{company_name}」の求人情報（職種: {title}）です。\n"
            "日本のハイエンドエンジニア向けに、日本語の職種名、リモート度('Full Remote'/'Hybrid'/'On-site')、"
            "年収/報酬表記、通貨、主要技術タグ（言語、クラウド等）、および2〜3行の簡潔な日本語要約を抽出し、指定スキーマで出力してください。\n\n"
            f"{raw_desc}"
        )

        response = client.models.generate_content(
            model="gemini-3.8-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=JobItem,
                temperature=0.2
            )
        )
        return JobItem.model_validate_json(response.text)
    except Exception as e:
        print(f"[GEMINI] パースエラー ({company_name}): {e}")
        return None

def run():
    jst = timezone(timedelta(hours=9))
    today_str = datetime.now(jst).strftime("%Y-%m-%d")

    print(f"=== 求人回収ボット開始 ({today_str}) ===")
    existing_jobs = load_jobs()
    existing_urls = {job.get("direct_apply_url") for job in existing_jobs}

    candidates = fetch_open_remote_candidates()
    print(f"-> 候補求人数: {len(candidates)} 件")

    new_count = 0
    # 1回の実行でGeminiを呼ぶ上限（API制限・時間配慮で5件程度に設定）
    limit_per_run = 5 

    for item in candidates:
        if new_count >= limit_per_run:
            break

        url = item["apply_url"]
        company = item["company"]
        title = item["raw_title"]

        if not url or url in existing_urls:
            continue

        print(f"\n[PARSE] 解析中: {company} - {title}")
        parsed = parse_with_gemini(company, title, item["raw_desc"])

        if parsed:
            job_record = {
                "id": f"{int(time.time())}_{len(existing_jobs) + 1}",
                "company": company,
                "title": parsed.title_ja or title,
                "currency": parsed.currency,
                "salary_display": parsed.salary_range or "応相談",
                "remote_type": parsed.remote_type,
                "tags": parsed.tags,
                "summary": parsed.summary_ja,
                "direct_apply_url": url,
                "is_featured": False,
                "published_at": today_str,
                "is_active": True
            }
            existing_jobs.insert(0, job_record)
            existing_urls.add(url)
            new_count += 1
            print(f"[SUCCESS] {company} | {job_record['title']} | {job_record['remote_type']}")

        time.sleep(1)

    if new_count > 0:
        save_jobs(existing_jobs)
        print(f"\n=== {new_count} 件の新規求人を jobs.json に反映しました ===")
    else:
        print("\n=== 新規求人はありませんでした ===")

if __name__ == "__main__":
    run()
