import datetime
import json
import re
import requests

TARGET_COMPANIES = {
    "greenhouse": [
        "binance",
        "gitlab",
        "stripe",
        "airbnb",
        "notion",
        "figma",
        "github",
        "reddit",
        "docker"
    ],
    "lever": [
        "spotify",
        "palantir",
        "cloudflare",
        "datadog",
        "netflix",
        "atlassian",
        "canva"
    ],
    "ashby": [
        "anthropic",
        "linear",
        "cursor",
        "openai",
        "perplexity",
        "ramp",
        "replit"
    ]
}

# --- 為替レート＆取得日時をグローバルに取得 ---
def get_current_usd_jpy_rate_info() -> dict:
    url = "https://open.er-api.com/v6/latest/USD"
    # 日本時間（JST）の現在日時文字列
    jst = datetime.timezone(datetime.timedelta(hours=9))
    now_jst_str = datetime.datetime.now(jst).strftime("%Y/%m/%d %H:%M JST")
    
    try:
        res = requests.get(url, timeout=6)
        if res.ok:
            data = res.json()
            rate = data.get("rates", {}).get("JPY")
            # API側の更新日時があれば利用、なければ現在取得日時
            time_last_update = data.get("time_last_update_utc", "")
            if rate:
                rate_val = round(float(rate), 2)
                print(f"[為替レート自動取得成功] 1 USD = {rate_val} JPY ({now_jst_str})")
                return {
                    "rate": rate_val,
                    "fetched_at": now_jst_str
                }
    except Exception as e:
        print(f"[為替レート取得警告] API接続失敗 ({e})。フォールバック値を使用")
    
    return {
        "rate": 150.0,
        "fetched_at": now_jst_str
    }

RATE_INFO = get_current_usd_jpy_rate_info()
CURRENT_RATE = RATE_INFO["rate"]

RATE_INFO = get_current_usd_jpy_rate_info()
CURRENT_RATE = RATE_INFO["rate"]

def extract_salary_range(text: str) -> dict:
    """米ドル（USD / $）表記のみを厳格に抽出。他国通貨（PLN, EUR, GBP等）は完全除外"""
    if not text:
        return None

    # HTMLタグと不要な空白の整理
    clean = re.sub(r"<[^>]+>", " ", text)
    clean = clean.replace("&nbsp;", " ").replace("&mdash;", "-").replace("&ndash;", "-")
    clean = clean.replace("&#36;", "$").replace("&dollar;", "$")
    clean = re.sub(r"[\u2010\u2011\u2012\u2013\u2014\u2015\u2212\uFF0D\u301C\u007E]+", "-", clean)
    clean = re.sub(r"\s+", " ", clean)

    # 1. $120,000 - $180,000 または $120k - $180k
    p1 = r"\$\s*([0-9]{2,3}(?:,[0-9]{3})*|[0-9]{2,3}(?:\.[0-9]+)?k)\s*(?:-|to)\s*\$\s*([0-9]{2,3}(?:,[0-9]{3})*|[0-9]{2,3}(?:\.[0-9]+)?k)"
    match = re.search(p1, clean, re.IGNORECASE)

    # 2. $120,000 - 180,000 USD (先頭に$があり、末尾にUSDまたは数字)
    if not match:
        p2 = r"\$\s*([0-9]{2,3}(?:,[0-9]{3})*)\s*(?:-|to)\s*([0-9]{2,3}(?:,[0-9]{3})*)\s*(?:USD)?"
        match = re.search(p2, clean, re.IGNORECASE)

    # 3. United States Salary Range: 120,000 - 180,000 USD のように前後にUSD/USが明記されているもの
    if not match:
        p3 = r"(?:United States|US)\s*(?:base\s*)?salary\s*range\s*:\s*\$?\s*([0-9]{2,3}(?:,[0-9]{3})*)\s*(?:-|to)\s*\$?\s*([0-9]{2,3}(?:,[0-9]{3})*)\s*USD"
        match = re.search(p3, clean, re.IGNORECASE)

    if not match:
        return None

    def parse_num(val_str: str) -> int:
        v = str(val_str).lower().replace(",", "").replace("$", "").strip()
        if "k" in v:
            return int(float(v.replace("k", "")) * 1000)
        return int(float(v))

    try:
        low = parse_num(match.group(1))
        high = parse_num(match.group(2))

        # 時給や極端な異常値を除外
        if low < 30000 or high > 2500000 or low >= high:
            return None

        jpy_low = round((low * CURRENT_RATE) / 100000) * 10
        jpy_high = round((high * CURRENT_RATE) / 100000) * 10

        return {
            "raw": f"${low:,} - ${high:,} USD",
            "usd_low": low,
            "usd_high": high,
            "jpy_approx": f"¥{jpy_low:,}万〜¥{jpy_high:,}万",
            "rate_applied": CURRENT_RATE,
            "rate_fetched_at": RATE_INFO["fetched_at"]
        }
    except Exception:
        return None

def extract_core_keywords(title: str) -> set:
    t = title.lower()
    t = re.sub(r"[\(\[\{].*?[\)\]\}]", " ", t)
    t = re.sub(r"[-–—/|:,]+", " ", t)
    stop_words = {
        "japan", "tokyo", "apac", "emea", "latam", "us", "remote",
        "hybrid", "onsite", "team", "growth", "group", "the", "and",
        "for", "with", "level", "grade", "ii", "iii", "iv", "sr"
    }
    words = [w.strip() for w in t.split() if len(w.strip()) >= 2 and w.strip() not in stop_words]
    return set(words)

def assign_japan_tags(title: str, location: str, workplace_type: str = "") -> list:
    loc = location.lower()
    text_corpus = f"{title} {location} {workplace_type}".lower()
    wp = workplace_type.lower()

    # 1. 日本国内（オフィス、国内リモート、国内ハイブリッド問わず）
    if any(k in loc for k in ["japan", "tokyo", "osaka", "kyoto", "日本", "東京", "大阪", "京都"]):
        return ["Japan"]

    # 2. 完全フルリモート（日本から在宅勤務可能な世界・広域枠）
    is_remote = any(k in text_corpus for k in ["remote", "anywhere", "worldwide", "global", "wfh"]) or wp == "remote"
    is_hybrid_or_onsite = any(k in text_corpus for k in ["hybrid", "onsite", "in-office", "in office"]) or wp in ["hybrid", "onsite"]
    
    # 【強化】海外の特定国限定リモート（米国・カナダ・英国等）を検知して除外
    country_restrictions = [
        "us only", "usa only", "remote - us", "remote, us", "remote - usa", "remote, usa",
        "united states", "u.s.", "canada only", "remote - canada", "uk only", "remote - uk",
        "germany only", "remote - germany", "australia only", "emea only"
    ]
    is_country_restricted = any(k in loc for k in country_restrictions)

    # 「完全世界リモート」または「国縛りのない広域リモート（APAC等）」のみを認定
    is_truly_global = any(k in loc for k in ["anywhere", "worldwide", "global", "all"]) or ("apac" in loc and not is_hybrid_or_onsite)

    if is_remote and not is_hybrid_or_onsite and not is_country_restricted and is_truly_global:
        return ["Global Remote"]

    # 3. 海外現地採用（日本国外の現地出社、現地ハイブリッド、海外限定リモート枠）
    # ※ Redditの全米リモート、OpenAIソウル、シンガポール、US現地などはすべてここに入ります
    if loc and loc != "not specified":
        return ["Overseas Local"]

    return ["Other"]

def is_us_location(location_str: str) -> bool:
    """求人勤務地が米国（US）であるかを厳格判定"""
    loc = location_str.lower()
    us_indicators = ["united states", "usa", "u.s.", ", us", "san francisco", "new york", "seattle", "austin", "remote - us", "us remote"]
    return any(ind in loc for ind in us_indicators)

def fetch_greenhouse(board_token: str) -> list:
    url = f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true"
    headers = {"Accept": "application/json"}
    try:
        res = requests.get(url, headers=headers, timeout=14)
        if not res.ok:
            return []
        data = res.json()
        results = []
        for posting in data.get("jobs", []):
            apply_url = posting.get("absolute_url", "").strip()
            if not apply_url:
                continue
            loc_data = posting.get("location")
            location = loc_data.get("name", "").strip() if isinstance(loc_data, dict) else str(loc_data or "").strip()
            title = posting.get("title", "").strip() or "Untitled"
            content = posting.get("content", "")
            
            # 給与の抽出（PLN等の他国通貨誤判定を防ぐ）
            salary = extract_salary_range(content)

            results.append({
                "ats": "Greenhouse",
                "company": board_token,
                "title": title,
                "location": location or "Not Specified",
                "tags": assign_japan_tags(title, location),
                "apply_url": apply_url,
                "salary": salary,
                "updated_at": posting.get("updated_at") or posting.get("first_published") or ""
            })
        print(f"[Greenhouse] {board_token}: {len(results)} jobs fetched (Salary: {sum(1 for r in results if r['salary'])})")
        return results
    except Exception as e:
        print(f"[Greenhouse] {board_token} error: {e}")
        return []

def fetch_lever(organization: str) -> list:
    url = f"https://api.lever.co/v0/postings/{organization}?mode=json"
    headers = {"Accept": "application/json"}
    try:
        res = requests.get(url, headers=headers, timeout=14)
        if not res.ok:
            return []
        postings = res.json()
        if not isinstance(postings, list):
            return []
        results = []
        for posting in postings:
            hosted_url = posting.get("hostedUrl", "").strip()
            if not hosted_url:
                continue
            categories = posting.get("categories", {})
            all_locations = categories.get("allLocations") or []
            if isinstance(all_locations, list) and len(all_locations) > 0:
                location = " / ".join([str(loc).strip() for loc in all_locations if str(loc).strip()])
            else:
                location = str(categories.get("location") or "").strip()
            workplace_type = str(categories.get("workplaceType") or "")
            title = posting.get("text", "").strip() or "Untitled"
            content = f"{posting.get('descriptionPlain', '')} {posting.get('additionalPlain', '')}"
            salary = extract_salary_range(content)

            created_at_ms = posting.get("createdAt")
            posting_date = ""
            if isinstance(created_at_ms, (int, float)) and created_at_ms > 0:
                dt = datetime.datetime.fromtimestamp(created_at_ms / 1000.0, tz=datetime.timezone.utc)
                posting_date = dt.strftime("%Y-%m-%dT%H:%M:%SZ")

            results.append({
                "ats": "Lever",
                "company": organization,
                "title": title,
                "location": location or "Not Specified",
                "tags": assign_japan_tags(title, location, workplace_type),
                "apply_url": hosted_url,
                "salary": salary,
                "updated_at": posting_date
            })
        print(f"[Lever] {organization}: {len(results)} jobs fetched (Salary: {sum(1 for r in results if r['salary'])})")
        return results
    except Exception as e:
        print(f"[Lever] {organization} error: {e}")
        return []

def fetch_ashby(company_slug: str) -> list:
    url = f"https://jobs.ashbyhq.com/{company_slug}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        res = requests.get(url, headers=headers, timeout=14)
        if not res.ok:
            return []
        match = re.search(r"window\.__appData\s*=\s*({.*?});", res.text, re.DOTALL) or re.search(r"window\.__appData\s*=\s*({.*)", res.text)
        if not match:
            return []
        data = json.loads(match.group(1))
        job_board = data.get("jobBoard") or {}
        job_postings = job_board.get("jobPostings") or []

        results = []
        for job in job_postings:
            if not isinstance(job, dict):
                continue
            job_id = job.get("id")
            if not job_id:
                continue
            location = job.get("locationName") or ""
            secondary = [loc.get("locationName") for loc in (job.get("secondaryLocations") or []) if isinstance(loc, dict) and loc.get("locationName")]
            if secondary:
                location = f"{location}, {', '.join(secondary)}" if location else ", ".join(secondary)
            workplace_type = str(job.get("workplaceType") or "")
            title = job.get("title", "").strip() or "Untitled"

            salary = None
            comp_tier = job.get("compensationTierSummary")
            if isinstance(comp_tier, dict):
                tier_min = comp_tier.get("min")
                tier_max = comp_tier.get("max")
                if tier_min and tier_max:
                    salary = extract_salary_range(f"${tier_min} - ${tier_max}")

            if not salary:
                comp_text = f"{job.get('compensationTierSummary', '')} {job.get('descriptionHtml', '')}"
                salary = extract_salary_range(comp_text)

            results.append({
                "ats": "Ashby",
                "company": company_slug,
                "title": title,
                "location": location.strip() or "Not Specified",
                "tags": assign_japan_tags(title, location, workplace_type),
                "apply_url": f"https://jobs.ashbyhq.com/{company_slug}/{job_id}",
                "salary": salary,
                "updated_at": job.get("publishedDate") or job.get("updatedAt") or ""
            })
        print(f"[Ashby] {company_slug}: {len(results)} jobs fetched (Salary: {sum(1 for r in results if r['salary'])})")
        return results
    except Exception as e:
        print(f"[Ashby] {company_slug} error: {e}")
        return []

def apply_us_reference_salary(all_jobs: list):
    """
    【最重要】
    参照元（ソース）として登録できるのは『米国（US）拠点の求人』のみに厳格制限。
    他国（ポーランド、英国、インド等）のローカル給与は絶対に参照元にしない。
    """
    company_salaries = {}
    for j in all_jobs:
        # 給与があり、かつ勤務地がUS（米国）であることが明らかな求人のみソース化
        if j.get("salary") and is_us_location(j.get("location", "")):
            comp = j["company"].lower()
            if comp not in company_salaries:
                company_salaries[comp] = []
            
            salary_data = dict(j["salary"])
            salary_data["source_url"] = j["apply_url"]
            salary_data["source_title"] = j["title"]
            company_salaries[comp].append({
                "keywords": extract_core_keywords(j["title"]),
                "title": j["title"],
                "salary": salary_data
            })

    matched_count = 0
    for j in all_jobs:
        if not j.get("salary"):
            comp = j["company"].lower()
            if comp in company_salaries:
                target_words = extract_core_keywords(j["title"])
                best_match = None
                best_score = 0

                for candidate in company_salaries[comp]:
                    overlap = len(target_words.intersection(candidate["keywords"]))
                    # 2語以上の一致、または主要役職単語を含む一致
                    if overlap > best_score and overlap >= 2:
                        best_score = overlap
                        best_match = candidate["salary"]
                    elif overlap > best_score and overlap >= 1 and any(w in target_words for w in ["architect", "engineer", "designer", "manager"]):
                        best_score = overlap
                        best_match = candidate["salary"]

                if best_match:
                    j["salary"] = best_match
                    j["salary_is_reference"] = True
                    matched_count += 1
        else:
            j["salary_is_reference"] = False
            j["salary"]["source_url"] = j["apply_url"]
            j["salary"]["source_title"] = j["title"]

    print(f"[Cross-Reference] 厳格突合完了: {matched_count} 件の求人に純粋な『米国(US)公開レンジ』を紐付けました。")

def main():
    all_jobs = []
    print("=== Greenhouse 求人取得開始 ===")
    for co in TARGET_COMPANIES["greenhouse"]:
        all_jobs.extend(fetch_greenhouse(co))

    print("\n=== Lever 求人取得開始 ===")
    for co in TARGET_COMPANIES["lever"]:
        all_jobs.extend(fetch_lever(co))

    print("\n=== Ashby 求人取得開始 ===")
    for co in TARGET_COMPANIES["ashby"]:
        all_jobs.extend(fetch_ashby(co))

    print("\n=== US給与レンジ突合処理開始 ===")
    apply_us_reference_salary(all_jobs)

    all_jobs.sort(key=lambda x: x.get("updated_at") or "", reverse=True)

    output_filename = "jobs.json"
    with open(output_filename, "w", encoding="utf-8") as f:
        json.dump(all_jobs, f, ensure_ascii=False, indent=2)

    print(f"\n完了: 合計 {len(all_jobs)} 件の求人を {output_filename} に保存しました。")

if __name__ == "__main__":
    main()