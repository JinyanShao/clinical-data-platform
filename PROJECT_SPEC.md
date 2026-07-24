# PROJECT_SPEC

## 1. Who uses it

- `Data Administrator`
- `Researcher`

## 2. What problem it solves

- Administrators import CSV or FHIR data.
- The system standardizes, validates, records errors, and preserves provenance.
- Researchers query approved data through the API.

## 3. v1 FHIR resources

- `Patient`
- `Encounter`
- `Observation`
- `ResearchStudy`

No additional FHIR resources are in v1.

## 4. Full v1 workflow

Upload CSV / FHIR Bundle -> Create Import Job -> Validate -> Transform -> Store -> Generate Error Report -> Query Data -> Audit Changes

## 5. What v1 does not do

- No real hospital system integration
- No real patient data
- No diagnosis
- No appointment scheduling
- No full EHR
- No AI
- No complex frontend
- No support for all FHIR resources

## Acceptance scenario

An administrator uploads a CSV with 100 synthetic laboratory records. The system successfully creates `Patient` and `Observation` records, rejects invalid rows with an error report, does not create duplicates on re-upload, shows import status and source records, and allows researchers to query the successfully imported data via API.
