# Bengaluru company career portals

This is a locally researched starter list, checked on 2026-10-21. Career pages and openings change; verify the employer page before applying.

## Official employer career portals

| Company | Bengaluru portal | App support today |
| --- | --- | --- |
| Amazon | [Bangalore jobs](https://amazon.jobs/content/en-gb/locations/india/bangalore) | Portal link only; its dynamic page may need a dedicated connector |
| Microsoft | [Bengaluru jobs](https://careers.microsoft.com/v2/global/en/locations/bengaluru.html) | Portal link only; its dynamic page may need a dedicated connector |
| Google | [Bengaluru jobs search](https://www.google.com/about/careers/applications/jobs/results/?location=Bangalore%2C+India) | Portal link only; its dynamic page may need a dedicated connector |
| Flipkart | [Current openings](https://www.flipkartcareers.com/jobslist) | Portal link only; its dynamic page may need a dedicated connector |

## Existing API connector boards

These portals match connectors already present in the app. The seed CSV includes the exact board URL; current postings should still be checked on the employer portal.

| Company | Board | Connector |
| --- | --- | --- |
| Acceldata | [Lever board](https://jobs.lever.co/acceldata) | Lever |
| Level AI | [Lever board](https://jobs.lever.co/levelai) | Lever |
| Endpoint Clinical | [Lever board](https://jobs.lever.co/endpointclinical) | Lever |
| Brillio | [Lever board](https://jobs.lever.co/brillio-2) | Lever |
| Sarvam | [Ashby board](https://jobs.ashbyhq.com/sarvam) | Ashby |
| Safe Security | [Lever board](https://jobs.lever.co/safe) | Lever |
| Universal Electronics | [Lever board](https://jobs.lever.co/uei) | Lever |
| Aeva | [Lever board](https://jobs.lever.co/aeva) | Lever |

## Local setup and collection

Import `major-company-career-portals.csv` using the admin company CSV import endpoint. The rows deliberately have `terms_reviewed=false`, so imported sources remain disabled. The four large-company portals are useful directory links, but the current generic crawler only collects supported structured job data; do not expect extraction from dynamic portals without a dedicated connector. Lever and Ashby rows use existing API connectors.

Before enabling any source, review that employer/ATS portal's applicable terms and robots policy and record the reviewed policy URL. The importer does not crawl during CSV import. After a source is reviewed and enabled in Admin, ingestion can be run locally through the admin source controls or API. Prefer direct employer application links when showing jobs to users.
