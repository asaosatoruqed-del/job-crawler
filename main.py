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
    title_ja: str = Field(description="日本語での職種名（例: シニアバックエンドエンジニア、プロダクトデザイナー）")
    remote_type: str = Field(description="リモート区分: 'Full Remote', 'Hybrid', 'On-site'")
    is_japan_eligible: bool = Field(description="日本国内在住のまま完全フルリモートで応募・勤務可能かどうか。特定国・都市限定（US Only, London現地等）なら必ずFalse")
    salary_range: Optional[str] = Field(description="想定年収や報酬表記（例: $100,000 - $140,000、または €80k - €110k。記載なしなら空文字）")
    currency: str = Field(description="通貨: 'USD', 'EUR', 'GBP', 'JPY', 'その他'")
    tags: List[str] = Field(description="主要技術や領域タグ（例: ['Go', 'AWS', 'FullRemote', 'USD']）")
    summary_ja: str = Field(description="日本の求職者向けにまとめた2〜3行の簡潔な業務要約・魅力")

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

def is_worldwide_location(loc_text: str) -> bool:
    if not loc_text:
        return True
    loc_lower = loc_text.lower()
    positive = ["worldwide", "anywhere", "remote", "global", "all"]
    negative = ["us only", "usa only", "uk only", "europe only", "eu only", "americas only", "canada only", "germany only"]
    
    if any(neg in loc_lower for neg in negative):
        return False
    return any(pos in loc_lower for pos in positive)

def fetch_open_remote_candidates() -> List[dict]:
    candidates = []
    
    # 1. Remotive API
    try:
        print("[FETCH] Remotive API から求人取得中...")
        res = requests.get("https://remotive.com/api/remote-jobs?category=software-dev&limit=25", headers=HEADERS, timeout=10)
        if res.status_code == 200:
            for item in res.json().get("jobs", []):
                req_loc = item.get("candidate_required_location", "")
                if is_worldwide_location(req_loc):
                    candidates.append({
                        "company": item.get("company_name"),
                        "raw_title": item.get("title"),
                        "location_info": req_loc or "Worldwide",
                        "raw_desc": clean_html(item.get("description", "")),
                        "apply_url": item.get("url"),
                        "source": "Remotive"
                    })
    except Exception as e:
        print(f"[WARN] Remotive 取得失敗: {e}")

    # 2. Arbeitnow API
    try:
        print("[FETCH] Arbeitnow API から求人取得中...")
        res = requests.get("https://www.arbeitnow.com/api/job-board-api", headers=HEADERS, timeout=10)
        if res.status_code == 200:
            for item in res.json().get("data", []):
                if item.get("remote") is True:
                    loc = item.get("location", "")
                    if is_worldwide_location(loc):
                        candidates.append({
                            "company": item.get("company_name"),
                            "raw_title": item.get("title"),
                            "location_info": loc or "Remote",
                            "raw_desc": clean_html(item.get("description", "")),
                            "apply_url": item.get("url"),
                            "source": "Arbeitnow"
                        })
    except Exception as e:
        print(f"[WARN] Arbeitnow 取得失敗: {e}")

    return candidates

def parse_with_gemini(company_name: str, title: str, location_info: str, raw_desc: str) -> Optional[JobItem]:
    if not GEMINI_API_KEY or not raw_desc.strip():
        return None

    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        prompt = (
            f"以下は企業「{company_name}」の求人情報（職種: {title}、提示地域: {location_info}）です。\n"
            "日本のハイエンドエンジニア向けに解析し、指定スキーマで出力してください。\n"
            "【判定基準】\n"
            "- is_japan_eligible: 日本在住のまま出社なしで完全リモート勤務できる場合は True。特定の国や都市（ロンドン、米国等）への現地居住・定期出社が前提のものは必ず False にしてください。\n"
            "- remote_type: 完全リモートなら 'Full Remote'。\n"
            "- tags: 主要言語、クラウド、領域、通貨（#USD等）などをタグ化してください。\n\n"
            f"{raw_desc}"
        )

        response = client.models.generate_content(
            model="gemini-2.5-flash",
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

    print(f"=== Worldwide求人回収ボット開始 ({today_str}) ===")
    existing_jobs = load_jobs()
    existing_urls = {job.get("direct_apply_url") for job in existing_jobs}

    candidates = fetch_open_remote_candidates()
    print(f"-> 事前スクリーニング通過候補: {len(candidates)} 件")

    new_count = 0
    limit_per_run = 8

    for item in candidates:
        if new_count >= limit_per_run:
            break

        url = item["apply_url"]
        company = item["company"]
        title = item["raw_title"]

        if not url or url in existing_urls:
            continue

        print(f"\n[PARSE] 厳格チェック中: {company} - {title} ({item['location_info']})")
        parsed = parse_with_gemini(company, title, item["location_info"], item["raw_desc"])

        if parsed:
            if not parsed.is_japan_eligible:
                print(f"[SKIP] 日本からのフルリモート不可（対象国限定または現地勤務）: {company}")
                continue

            final_tags = list(set(parsed.tags + ["Worldwide", parsed.currency]))

            job_record = {
                "id": f"{int(time.time())}_{len(existing_jobs) + 1}",
                "company": company,
                "title": parsed.title_ja or title,
                "currency": parsed.currency,
                "salary_display": parsed.salary_range or "応相談",
                "remote_type": parsed.remote_type,
                "location_scope": "Worldwide (日本在住可)",
                "tags": final_tags,
                "summary": parsed.summary_ja,
                "direct_apply_url": url,
                "is_featured": False,
                "published_at": today_str,
                "is_active": True
            }
            existing_jobs.insert(0, job_record)
            existing_urls.add(url)
            new_count += 1
            print(f"[SUCCESS] 日本在住OK求人を登録: {company} | {job_record['title']} | 給与: {job_record['salary_display']}")

        time.sleep(1)

    if new_count > 0:
        save_jobs(existing_jobs)
        print(f"\n=== {new_count} 件の厳選Worldwide求人を jobs.json に反映しました ===")
    else:
        print("\n=== 新規のWorldwide求人はありませんでした ===")

if __name__ == "__main__":
    run()
