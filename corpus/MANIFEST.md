# Corpus Manifest

Documents for RAHBAR — FAST-NUCES public site, checked 2026-11-01.
PDFs are **not committed**; download with `python corpus/fetch.py`.

| File | URL | SHA-256 | doc_version | superseded |
|------|-----|---------|-------------|------------|
| academic-rules-handbook-2026.pdf | https://nu.edu.pk/public/downloads/Academic_Rules_Handbook_June_2026.pdf | 608a0397e8a3545712bef7f17946dcda3613525b953ce40a64d32b506b2208e7 | 2026-06 | false |
| undergraduate-academic-rules-2023.pdf | https://nu.edu.pk/public/downloads/Undergraduate_Academic_Rules_Aug_2023.pdf | c9394e369f0e6fe65a925a77db99fa5728b2738335adbe5c18664c070ccf94de | 2023-08 | true |
| student-handbook-2026.pdf | https://nu.edu.pk/public/downloads/Student_Handbook_June_2026.pdf | 6f60611cc3c4148e3805ddaf92e3db8e21d62cb2078d02e7c3c23d5b3ca88386 | 2026-06 | false |
| annual-report-2019-20.pdf | https://nu.edu.pk/public/downloads/Annual_Report_2019-20.pdf | c602a786315e5857070bcd549be57b85ab911b6267d075e7fb056f0f6067b8b9 | 2019-20 | true |
| annual-report-2023-24.pdf | https://nu.edu.pk/public/downloads/Annual_Report_2023-24.pdf | 84114abdacd90d22162ee278de754e4262ff4329c5be94ca1a150d8034b397a5 | 2023-24 | false |
| faculty-entrepreneurship-policy.pdf | https://nu.edu.pk/OricResources/ResearchPolicies/Faculty_Entrepreneurship_and_Technical_Startups_Policy.pdf | 857e5cffe16f368b77f87eb80a128baf835695bf69d9f61f920df5cd48363599 | 2022 | false |
| fee-structure.html | https://nu.edu.pk/Admissions/FeeStructure | 53fb37d7e1454ebf0a89357a5febe82fcfcf772c542a1da8c256e012c12a2d31 | 2026 | false |
| prospectus-2026.pdf | https://nu.edu.pk/Admissions/ProspectusUpload/FAST_Prospectus_2026.pdf | 8872caa5b77a4c6fb606f25cdee677619a8f52f1366eacee56c48fdae562e284 | 2026 | false |

## Deliberately absent

The **hostel/transport facilities** document is excluded to test honest abstention (failure mode 6).
Questions about hostel room allocation or transport should return `answered_from_context: false`.

## Download

```bash
python corpus/fetch.py --sources corpus/sources.yaml
```
