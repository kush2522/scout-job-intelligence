from urllib.parse import urlparse, urljoin
import httpx
from bs4 import BeautifulSoup
from .connectors import assert_public_http_url, safe_get, robots_allowed
from .config import settings

def connector_for_url(url: str, company_name: str | None = None):
    p = urlparse(url); host = (p.hostname or "").lower(); parts = [x for x in p.path.split("/") if x]
    base = {"company_name": company_name} if company_name else {}
    if host in {"boards.greenhouse.io", "job-boards.greenhouse.io"} and parts:
        return {"kind":"greenhouse", "name":company_name or parts[0], "base_url":url, "config_json":{**base,"board_token":parts[0]}}
    if host in {"jobs.lever.co", "jobs.eu.lever.co"} and parts:
        return {"kind":"lever", "name":company_name or parts[0], "base_url":url, "config_json":{**base,"site":parts[0]}}
    if host == "jobs.ashbyhq.com" and parts:
        return {"kind":"ashby", "name":company_name or parts[0], "base_url":url, "config_json":{**base,"job_board_name":parts[0]}}
    if host == "careers.smartrecruiters.com" and parts:
        return {"kind":"smartrecruiters", "name":company_name or parts[0], "base_url":url, "config_json":{**base,"company_identifier":parts[0]}}
    if host == "api.lever.co" and len(parts) >= 3 and parts[:2] == ["v0", "postings"]:
        return {"kind":"lever", "name":company_name or parts[2], "base_url":url, "config_json":{**base,"site":parts[2]}}
    if host == "api.smartrecruiters.com" and "companies" in parts:
        i = parts.index("companies")
        if len(parts) > i+1:
            return {"kind":"smartrecruiters", "name":company_name or parts[i+1], "base_url":url, "config_json":{**base,"company_identifier":parts[i+1]}}
    return {"kind":"career_page", "name":company_name or host, "base_url":url, "config_json":{**base,"max_pages":settings.max_career_pages}}

async def discover_careers(website_url: str, company_name: str | None = None):
    """Suggest permitted source candidates from a company home page; never auto-registers a source."""
    assert_public_http_url(website_url)
    headers={"User-Agent":settings.user_agent,"Accept":"text/html,application/xhtml+xml"}
    async with httpx.AsyncClient(headers=headers, timeout=settings.request_timeout_seconds) as client:
        if not await robots_allowed(client, website_url):
            raise PermissionError("robots.txt does not permit fetching the supplied website URL")
        response=await safe_get(client, website_url)
        response.raise_for_status()
        soup=BeautifulSoup(response.text,"html.parser")
        origin=f"{urlparse(website_url).scheme}://{urlparse(website_url).netloc}"
        found=[]; seen=set()
        def add_candidate(candidate, label="career link"):
            candidate = candidate.split("#",1)[0]
            if not candidate or candidate in seen: return
            try: assert_public_http_url(candidate)
            except Exception: return
            parsed=urlparse(candidate)
            if parsed.scheme not in {"http","https"}: return
            suggestion=connector_for_url(candidate, company_name)
            # Only keep actual public careers/vendor URLs, not arbitrary links from home pages.
            is_vendor=suggestion["kind"] != "career_page"
            is_career=is_vendor or any(word in (candidate+" "+label).lower() for word in ("career","job","vacanc","opening","position","work-with-us","join-us"))
            if is_career:
                seen.add(candidate); suggestion["label"]=label[:120]; found.append(suggestion)
        for a in soup.select("a[href]"):
            href=urljoin(website_url,a.get("href", "")); label=a.get_text(" ",strip=True) or href
            parsed=urlparse(href)
            host=(parsed.hostname or "").lower()
            # Detect only common hiring platforms or career-oriented same-site links.
            if host in {"boards.greenhouse.io","job-boards.greenhouse.io","jobs.lever.co","jobs.eu.lever.co","jobs.ashbyhq.com","careers.smartrecruiters.com","api.lever.co","api.smartrecruiters.com"}:
                add_candidate(href,label)
            elif parsed.netloc.lower()==urlparse(website_url).netloc.lower() and any(w in (label+" "+parsed.path).lower() for w in ("career","jobs","vacanc","opening","position","work-with-us","join-us")):
                add_candidate(href,label)
        # A few conventional career paths are probed, but only when robots.txt permits them.
        for path in ("/careers", "/career", "/jobs", "/careers/jobs", "/work-with-us"):
            candidate=urljoin(origin,path)
            if candidate in seen or not await robots_allowed(client,candidate): continue
            try:
                r=await safe_get(client,candidate)
                if r.status_code==200 and "text/html" in r.headers.get("content-type","").lower():
                    add_candidate(candidate,path.strip("/"))
            except Exception:
                continue
        # Favor ATS endpoints over generic same-site pages; dedupe by connector + URL.
        unique={}
        for item in found: unique[(item["kind"],item["base_url"])]=item
        return {"website_url":website_url,"company_name":company_name,"suggestions":list(unique.values()),"count":len(unique)}
