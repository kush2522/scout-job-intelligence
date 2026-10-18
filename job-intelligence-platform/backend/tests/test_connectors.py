from app.connectors import canonicalize, normalize, normalize_jsonld, _jobposting_nodes

def test_canonicalize_strips_tracking_query_and_fragment():
    assert canonicalize("https://EXAMPLE.com/jobs/123?utm_source=foo#apply") == "https://example.com/jobs/123"

def test_normalize_is_case_and_space_insensitive():
    assert normalize("  Director   AI ") == "director ai"

def test_jobposting_jsonld_normalization():
    node={"@type":"JobPosting","title":"Staff Engineer","url":"https://jobs.example/123","hiringOrganization":{"name":"Example"},"jobLocation":{"address":{"addressLocality":"Bengaluru","addressCountry":"India"}}}
    item=normalize_jsonld(node,"Fallback","https://careers.example")
    assert item["title"] == "Staff Engineer"
    assert item["company_name"] == "Example"
    assert item["location"] == "Bengaluru, India"

def test_jsonld_graph_extracts_jobposting():
    nodes=list(_jobposting_nodes({"@graph":[{"@type":"Organization"},{"@type":"JobPosting","title":"Engineer"}]}))
    assert len(nodes)==1 and nodes[0]["title"]=="Engineer"
