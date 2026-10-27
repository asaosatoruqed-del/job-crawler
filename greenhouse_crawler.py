import json
import time
import requests

TARGET_BOARDS = [
    "gitlab",
    "alpaca",
    "docker",
    "duckduckgo",
    "binance",
    "automattic",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; GlobalRemoteJobBot/1.0)"
}

def is_valid_remote(location_name: str, title: str) -> bool:
    text = f"{location_name} {title}".lower()
    exclude_keywords = [
        "hybrid", "in person", "in-person", "on-site", "onsite", 
        "us only", "u.s. only", "united states only", "americas only"
    ]
    if any(k in text for k in exclude_keywords):
        return False

    allowed_keywords = [
        "japan", "tokyo", "apac", "asia", "global", "worldwide", "anywhere"
    ]
    return any(k in text for k in allowed_keywords)

def fetch_greenhouse_jobs():
    all_jobs = []

    for board in TARGET_BOARDS:
        url = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs"
        print(f"Fetching: {board} ({url})...")
        
        try:
            res = requests.get(url, headers=HEADERS, timeout=10)
            if res.status_code != 200:
                print(f"  [Skipped] HTTP {res.status_code}")
                continue
                
            data = res.json()
            raw_jobs = data.get("jobs", [])
            matched_count = 0

            for job in raw_jobs:
                title = job.get("title", "")
                loc_obj = job.get("location", {})
                loc_name = loc_obj.get("name", "") if isinstance(loc_obj, dict) else ""
                
                if is_valid_remote(loc_name, title):
                    all_jobs.append({
                        "company": board.capitalize(),
                        "title": title,
                        "location": loc_name if loc_name else "Remote (Global/APAC)",
                        "url": job.get("absolute_url"),
                        "updated_at": job.get("updated_at", "")[:10],
                        "source": "Greenhouse"
                    })
                    matched_count += 1
            
            print(f"  -> 取得成功: 全{len(raw_jobs)}件中、適格案件 {matched_count}件")
            time.sleep(0.5)

        except Exception as e:
            print(f"  [Error] {board}: {e}")

    with open("jobs.json", "w", encoding="utf-8") as f:
        json.dump(all_jobs, f, ensure_ascii=False, indent=2)

    print(f"\n完了: 合計 {len(all_jobs)} 件の完全リモート求人を jobs.json に保存しました。")

if __name__ == "__main__":
    fetch_greenhouse_jobs()