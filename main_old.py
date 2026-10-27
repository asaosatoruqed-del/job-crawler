import os
import json
import time
from datetime import datetime, timezone, timedelta
from typing import List
import requests
from bs4 import BeautifulSoup

JOBS_FILE = "jobs.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

# 即死キーワード（含まれていたら問答無用で除外）
EXCLUDE_KEYWORDS = [
    "us only", "usa only", "uk only", "europe only", "eu only",
    "americas only", "canada only", "germany only", "latin america",
    "us citizenship", "green card", "security clearance", "hybrid", "on-site",
    "no c2c", "w2 only", "must reside in the us", "must reside in europe"
]

# Worldwide判定キーワード（いずれかが含まれていれば候補とする）
WORLDWIDE_KEYWORDS = [
    "worldwide", "anywhere", "global", "remote - anywhere", "all countries", "work from anywhere"
]

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
    text = soup.get_text(separator=" ", strip=True)
    return " ".join(text.split())

def is_worldwide_candidate(loc_text: str, desc_text: str) -> bool:
    target_text = f"{loc_text} {desc_text}".lower()

    # 1. 除外キーワードに引っかかったら即NG
    if any(neg in target_text for neg in EXCLUDE_KEYWORDS):
        return False

    # 2. 勤務地または本文にWorldwide系の言葉が入っていれば候補とする
    loc_lower = loc_text.lower()
    if any(pos in loc_lower for pos in WORLDWIDE_KEYWORDS):
        return True
    
    if any(pos in target_text for pos in WORLDWIDE_KEYWORDS):
        return True

    return False

def fetch_open_remote_candidates() -> List[dict]:
    candidates = []

    # 1. Remotive API
    try:
        print("[FETCH] Remotive API から求人取得中...")
        res = requests.get("https://remotive.com/api/remote-jobs?category=software-dev&limit=40", headers=HEADERS, timeout=10)
        if res.status_code == 200:
            for item in res.json().get("jobs", []):
                req_loc = item.get("candidate_required_location", "")
                raw_desc = clean_html(item.get("description", ""))
                
                if is_worldwide_candidate(req_loc, raw_desc):
                    candidates.append({
                        "company": item.get("company_name"),
                        "raw_title": item.get("title"),
                        "location_info": req_loc or "Worldwide",
                        "raw_desc": raw_desc[:500], # 目視用に冒頭だけ保持
                        "apply_url": item.get("url"),
                        "tags": item.get("tags", []),
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
                    raw_desc = clean_html(item.get("description", ""))
                    
                    if is_worldwide_candidate(loc, raw_desc):
                        candidates.append({
                            "company": item.get("company_name"),
                            "raw_title": item.get("title"),
                            "location_info": loc or "Remote",
                            "raw_desc": raw_desc[:500],
                            "apply_url": item.get("url"),
                            "tags": item.get("tags", []),
                            "source": "Arbeitnow"
                        })
    except Exception as e:
        print(f"[WARN] Arbeitnow 取得失敗: {e}")

    return candidates

def run():
    jst = timezone(timedelta(hours=9))
    today_str = datetime.now(jst).strftime("%Y-%m-%d")

    print(f"=== キーワード足切りクローラー開始 ({today_str}) ===")
    existing_jobs = load_jobs()
    existing_urls = {job.get("direct_apply_url") for job in existing_jobs}

    candidates = fetch_open_remote_candidates()
    print(f"-> 候補求人件数: {len(candidates)} 件")

    new_count = 0

    for item in candidates:
        url = item["apply_url"]
        company = item["company"]
        title = item["raw_title"]

        if not url or url in existing_urls:
            continue

        job_record = {
            "id": f"{int(time.time())}_{len(existing_jobs) + 1}",
            "company": company,
            "title": title,
            "currency": "USD",
            "salary_display": "要確認（目視チェック待ち）",
            "remote_type": "Full Remote",
            "location_scope": item["location_info"],
            "tags": list(set(item["tags"] + ["Worldwide", "要目視確認"])),
            "summary": item["raw_desc"],
            "direct_apply_url": url,
            "is_featured": False,
            "published_at": today_str,
            "is_active": True
        }

        existing_jobs.insert(0, job_record)
        existing_urls.add(url)
        new_count += 1
        print(f"[PICK] 候補追加: {company} | {title} ({item['location_info']})")

    if new_count > 0:
        save_jobs(existing_jobs)
        print(f"\n=== {new_count} 件の候補求人を jobs.json に保存しました（API消費: 0円） ===")
    else:
        print("\n=== 新規の候補求人はありませんでした ===")

if __name__ == "__main__":
    run()
