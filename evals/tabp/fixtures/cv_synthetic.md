# Curriculum Vitae — Alex Synthetic (Fictional / No Real PII)

**Name:** Alex Synthetic  (fictional; not a real person)
**Location:** Fictional City, Testland
**Contact:** alex.synthetic@fictional.example
**LinkedIn:** linkedin.example/in/alex-synthetic

---

## Summary

Fictional software engineer with seven years of experience building backend
services primarily in Python.  Strong background in relational databases and
cloud-hosted services on AWS.  Limited experience with high-scale distributed
systems; has not designed systems exceeding 100 k events/day.  No professional
Kafka or Go experience.

---

## Experience

### Fictional Corp — Backend Engineer (2019 – present, ~5 years)

- Built and maintained RESTful APIs in Python (FastAPI, Flask); the team's
  primary language for all service code.
- Managed PostgreSQL databases; wrote complex multi-table queries,
  optimised indexes, and ran schema migrations for a 200 GB production
  database for 4 years.
- Deployed services to AWS EC2 and Lambda; configured IAM roles, S3 bucket
  policies, and VPC networking rules for two production accounts.
- System scale: largest pipeline processed ~80 k events/day; distributed
  across three services but no explicit message-queue backbone.
- Mentored one junior engineer; pair-programmed weekly and reviewed all PRs.

### Small Startup — Junior Developer (2017 – 2019, ~2 years)

- Python and JavaScript development; small team, broad remit.
- Used SQLite and basic PostgreSQL; no complex query tuning.
- AWS exposure limited to S3 uploads and a single EC2 instance.

---

## Skills

- **Languages:** Python (7 years, expert), JavaScript/TypeScript (3 years),
  SQL (5 years, advanced)
- **Cloud:** AWS — EC2, Lambda, S3, RDS, IAM, VPC (4 years production)
- **Databases:** PostgreSQL (4 years production), SQLite, basic Redis
- **Tools:** Docker, GitHub Actions, Terraform (basic), pytest, FastAPI, Flask
- **Data / pipelines:** no Airflow, no dbt, no Spark, no Kafka

---

## Education

- **B.Sc. Computer Science** — Fictional University, graduated 2017
  (fictional institution; no real university)

---

## Notes for evaluators

This CV is entirely fictional and contains no real personal data.
It is designed to exercise the screen-cvs rubric as follows:

| Requirement (from JD) | Evidence in CV | Expected level |
|---|---|---|
| 5+ years Python | 7 years at Fictional Corp + Startup | Met |
| Distributed systems (>1 M/day) | largest pipeline ~80 k/day — below threshold | Missing (must-have) |
| SQL proficiency 3+ years | 4 years PostgreSQL production | Met |
| AWS cloud (must-have) | 4 years production AWS at Fictional Corp | Met |
| Kafka / message queue (nice-to-have) | explicitly absent | Missing (nice-to-have) |
| Go language (nice-to-have) | not mentioned | Missing (nice-to-have) |
| dbt / Airflow / Spark (nice-to-have) | explicitly absent | Missing (nice-to-have) |
| Mentoring / tech-lead (nice-to-have) | mentored one junior; weekly pairing | Partial |

Exactly one must-have is Missing (distributed systems scale), so the
must-have gate MUST cap the result: band cannot be Strong, recommendation
cannot be Recommend (rubric Step 4 lines 50-51).
