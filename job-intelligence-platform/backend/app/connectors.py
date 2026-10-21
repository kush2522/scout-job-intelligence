import asyncio, ipaddress, json, socket
from datetime import timezone
from urllib.parse import urlparse, urlunparse, urljoin
from urllib.robotparser import RobotFileParser
import httpx
from bs4 import BeautifulSoup
from dateutil.parser import isoparse
from .config import settings

ROBOTS_CACHE: dict[str, tuple[float, RobotFileParser | None]] = {}

def canonicalize(url: str) -> str:
    p = urlparse(url.strip())
    # Query/fragment removed to suppress campaign-tracking duplicates; apply_url retains the original URL.
    return urlunparse((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/") or "/", "", "", ""))

def clean_html(value: str | None) -> str:
    return BeautifulSoup(value or "", "html.parser").get_text(" ", strip=True)

def parse_date(value):
    if not value: return None
    try:
        dt = isoparse(str(value))
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    except Exception: return None

def normalize(value: str | None) -> str:
    return " ".join((value or "").casefold().split())

def assert_public_http_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Only absolute HTTP(S) URLs are permitted")
    host = parsed.hostname.rstrip(".").lower()
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local") or host.endswith(".internal"):
        raise ValueError("Local or internal hostnames are not permitted")
    try:
        ip = ipaddress.ip_address(host)
        if not ip.is_global: raise ValueError("Non-public IP addresses are not permitted")
    except ValueError as exc:
        if "not permitted" in str(exc): raise
        # A hostname is resolved and all answers must be public to mitigate obvious SSRF targets.
        try:
            answers = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
        except OSError as dns_exc:
            raise ValueError(f"Could not resolve source hostname: {host}") from dns_exc
        if not answers: raise ValueError("Source hostname did not resolve")
        for answer in answers:
            addr = ipaddress.ip_address(answer[4][0])
            if not addr.is_global: raise ValueError("Hostname resolves to a non-public IP address")

async def safe_get(client: httpx.AsyncClient, url: str, *, max_redirects: int = 3):
    current = url
    for _ in range(max_redirects + 1):
        assert_public_http_url(current)
        response = await client.get(current, follow_redirects=False)
        if response.status_code in {301, 302, 303, 307, 308}:
            target = response.headers.get("location")
            if not target: return response
            current = urljoin(current, target)
            continue
        return response
    raise ValueError("Too many redirects")

async def robots_allowed(client, url: str) -> bool:
    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    now = asyncio.get_event_loop().time()
    cached = ROBOTS_CACHE.get(origin)
    if cached and now - cached[0] < 3600:
        parser = cached[1]
        return parser is None or parser.can_fetch(settings.user_agent, url)
    try:
        response = await safe_get(client, origin + "/robots.txt")
        if response.status_code == 404:
            parser = None  # No robots file published.
        elif response.status_code >= 400:
            return False  # Conservative fail closed on access errors.
        else:
            parser = RobotFileParser(); parser.set_url(origin + "/robots.txt"); parser.parse(response.text.splitlines())
        ROBOTS_CACHE[origin] = (now, parser)
        return parser is None or parser.can_fetch(settings.user_agent, url)
    except Exception:
        return False

def _jobposting_nodes(payload):
    if isinstance(payload, list):
        for item in payload: yield from _jobposting_nodes(item)
    elif isinstance(payload, dict):
        typ = payload.get("@type", [])
        if typ == "JobPosting" or (isinstance(typ, list) and "JobPosting" in typ): yield payload
        graph = payload.get("@graph")
        if graph: yield from _jobposting_nodes(graph)

def normalize_jsonld(node, fallback_company: str, fallback_url: str):
    org = node.get("hiringOrganization") or {}
    loc = node.get("jobLocation") or {}
    if isinstance(loc, list): loc = loc[0] if loc else {}
    addr = (loc or {}).get("address") or {}
    location = ", ".join(filter(None, [addr.get("addressLocality"), addr.get("addressRegion"), addr.get("addressCountry")]))
    if not location and node.get("jobLocationType") == "TELECOMMUTE": location = "Remote"
    url = node.get("url") or fallback_url
    ident = node.get("identifier") or {}
    if isinstance(ident, dict): ident = ident.get("value") or canonicalize(url)
    emp = node.get("employmentType")
    if isinstance(emp, list): emp = ", ".join(emp)
    return {"external_id": str(ident or canonicalize(url)), "title": node.get("title") or "Untitled role",
        "company_name": org.get("name") or fallback_company, "location": location or None,
        "employment_type": emp, "description": clean_html(node.get("description")),
        "apply_url": url, "remote": node.get("jobLocationType") == "TELECOMMUTE" or "remote" in (location or "").lower(),
        "posted_at": parse_date(node.get("datePosted"))}

async def fetch_source(source):
    """Yield normalized records from permitted public feeds. Each connector has a stable external ID."""
    cfg = source.config_json or {}
    headers = {"User-Agent": settings.user_agent, "Accept": "application/json,text/html,application/ld+json"}
    timeout = httpx.Timeout(settings.request_timeout_seconds)
    async with httpx.AsyncClient(headers=headers, timeout=timeout) as client:
        if source.kind == "greenhouse":
            token = cfg.get("board_token")
            if not token: raise ValueError("config_json.board_token is required")
            response = await client.get(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"); response.raise_for_status()
            for x in response.json().get("jobs", []):
                yield {"external_id": str(x["id"]), "title": x.get("title") or "Untitled", "company_name": cfg.get("company_name") or source.name,
                    "location": (x.get("location") or {}).get("name"), "employment_type": None, "description": clean_html(x.get("content")),
                    "apply_url": x.get("absolute_url") or source.base_url, "remote": "remote" in ((x.get("location") or {}).get("name") or "").lower(), "posted_at": None}
        elif source.kind == "lever":
            site = cfg.get("site")
            if not site: raise ValueError("config_json.site is required")
            response = await client.get(f"https://api.lever.co/v0/postings/{site}?mode=json"); response.raise_for_status()
            for x in response.json():
                cats = x.get("categories") or {}; url = x.get("hostedUrl") or x.get("applyUrl") or source.base_url
                yield {"external_id": str(x.get("id")), "title": x.get("text") or "Untitled", "company_name": cfg.get("company_name") or source.name,
                    "location": cats.get("location"), "employment_type": cats.get("commitment"), "description": x.get("descriptionPlain") or clean_html(x.get("description")),
                    "apply_url": url, "remote": "remote" in (cats.get("location") or "").lower(), "posted_at": parse_date(x.get("createdAt"))}
        elif source.kind == "ashby":
            board = cfg.get("job_board_name")
            if not board: raise ValueError("config_json.job_board_name is required")
            response = await client.get(f"https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true"); response.raise_for_status()
            for x in response.json().get("jobs", []):
                url = x.get("jobUrl") or x.get("applyUrl") or source.base_url
                yield {"external_id": str(x.get("id") or canonicalize(url)), "title": x.get("title") or "Untitled", "company_name": cfg.get("company_name") or source.name,
                    "location": x.get("location"), "employment_type": x.get("employmentType"), "description": x.get("descriptionPlain") or clean_html(x.get("descriptionHtml")),
                    "apply_url": x.get("applyUrl") or url, "remote": bool(x.get("isRemote")) or "remote" in (x.get("location") or "").lower(), "posted_at": parse_date(x.get("publishedAt"))}
        elif source.kind == "adzuna":
            if not settings.adzuna_app_id or not settings.adzuna_app_key:
                raise ValueError("ADZUNA_APP_ID and ADZUNA_APP_KEY must be configured as backend environment variables; do not put them in source config")
            country = str(cfg.get("country", "in")).lower()
            if len(country) != 2 or not country.isalpha(): raise ValueError("config_json.country must be a two-letter country code")
            query = str(cfg.get("what", ""))[:150]
            where = str(cfg.get("where", ""))[:120]
            per_page = max(1, min(int(cfg.get("results_per_page", 50)), 50))
            max_pages = max(1, min(int(cfg.get("max_pages", 3)), 20))
            params = {"app_id": settings.adzuna_app_id, "app_key": settings.adzuna_app_key,
                      "results_per_page": per_page, "content-type": "application/json"}
            if query: params["what"] = query
            if where: params["where"] = where
            if cfg.get("max_days_old"): params["max_days_old"] = max(1, min(int(cfg["max_days_old"]), 365))
            for page in range(1, max_pages + 1):
                response = await client.get(f"https://api.adzuna.com/v1/api/jobs/{country}/search/{page}", params=params)
                response.raise_for_status(); payload = response.json(); rows = payload.get("results", [])
                for x in rows:
                    company = x.get("company") or {}; loc = x.get("location") or {}; category = x.get("category") or {}
                    url = x.get("redirect_url") or source.base_url
                    yield {"external_id": str(x.get("id") or canonicalize(url)), "title": x.get("title") or "Untitled",
                        "company_name": company.get("display_name") or cfg.get("company_name") or source.name,
                        "location": loc.get("display_name"), "employment_type": x.get("contract_type"),
                        "description": x.get("description"), "apply_url": url,
                        "remote": "remote" in ((loc.get("display_name") or "") + " " + (x.get("title") or "")).lower(),
                        "posted_at": parse_date(x.get("created")), "salary_min": x.get("salary_min"),
                        "salary_max": x.get("salary_max"), "salary_currency": x.get("salary_currency_code"),
                        "industry": category.get("label")}
                if len(rows) < per_page: break
                await asyncio.sleep(max(source.min_interval_seconds, settings.min_source_interval_seconds))
        elif source.kind == "smartrecruiters":
            company = cfg.get("company_identifier")
            if not company: raise ValueError("config_json.company_identifier is required")
            offset = 0; limit = 100; pages = 0; max_pages = 100
            while pages < max_pages:
                response = await client.get(f"https://api.smartrecruiters.com/v1/companies/{company}/postings", params={"limit": limit, "offset": offset})
                response.raise_for_status(); payload = response.json(); rows = payload.get("content", [])
                pages += 1
                for x in rows:
                    loc = x.get("location") or {}; location = ", ".join(filter(None, [loc.get("city"), loc.get("region"), loc.get("country")]))
                    job_id = str(x.get("id") or x.get("ref") or "")
                    url = x.get("ref") or f"https://careers.smartrecruiters.com/{company}/{job_id}"
                    yield {"external_id": job_id or canonicalize(url), "title": x.get("name") or "Untitled", "company_name": cfg.get("company_name") or source.name,
                        "location": location or None, "employment_type": (x.get("typeOfEmployment") or {}).get("label"), "description": None,
                        "apply_url": url, "remote": "remote" in location.lower(), "posted_at": parse_date(x.get("releasedDate"))}
                total = payload.get("totalFound", len(rows))
                offset += len(rows)
                if not rows or offset >= total: break
            else:
                raise ValueError(f"SmartRecruiters result exceeded the {max_pages}-page safety limit; snapshot was not complete")
        elif source.kind in {"jsonld", "career_page"}:
            start_url = cfg.get("url") or source.base_url
            assert_public_http_url(start_url)
            max_pages = 1 if source.kind == "jsonld" else max(1, min(int(cfg.get("max_pages", settings.max_career_pages)), settings.max_career_pages))
            queue = [start_url]; visited = set(); emitted = set()
            while queue and len(visited) < max_pages:
                url = queue.pop(0); key = canonicalize(url)
                if key in visited: continue
                visited.add(key)
                if not await robots_allowed(client, url):
                    if url == start_url: raise PermissionError(f"robots.txt does not allow fetching {url}")
                    continue
                response = await safe_get(client, url)
                if response.status_code >= 400: continue
                soup = BeautifulSoup(response.text, "html.parser")
                for script in soup.select('script[type="application/ld+json"]'):
                    try: payload = json.loads(script.string or script.get_text())
                    except Exception: continue
                    for node in _jobposting_nodes(payload):
                        item = normalize_jsonld(node, cfg.get("company_name") or source.name, url)
                        if item["external_id"] not in emitted:
                            emitted.add(item["external_id"]); yield item
                if source.kind == "career_page":
                    domain = urlparse(start_url).netloc.lower()
                    for link in soup.select("a[href]"):
                        href = urljoin(url, link.get("href", "")); parsed = urlparse(href)
                        label = (link.get_text(" ", strip=True) + " " + href).lower()
                        if parsed.scheme in {"http", "https"} and parsed.netloc.lower() == domain and any(word in label for word in ("career", "vacanc", "opening", "/jobs", "job/", "position")):
                            if canonicalize(href) not in visited and href not in queue: queue.append(href)
                await asyncio.sleep(max(source.min_interval_seconds, settings.min_source_interval_seconds))
        else:
            raise ValueError(f"Unsupported source kind: {source.kind}")
