# Document Intelligence Assessment

**Exported:** 2026-01-30T18:45:27.847233

**Assessment ID:** 3c2c188a-96d9-4fcb-9ee4-f45a14fe24fc

---

## Documents Processed (1)

- **tough_test_document.docx** (parsed)
  - Sections: 9

---

## Extracted Truths (24)


### tough_test_document.docx

**ASSERTION** (confidence: 90%)

> Processes retail banking transactions for approximately 2.3 million customers

*Source: System Overview, page None*


**ASSERTION** (confidence: 85%)

> Q2 board presentation stated 2.1 million customers

*Source: System Overview, page None*


**ASSERTION** (confidence: 95%)

> Core banking module runs on IBM z/OS mainframe infrastructure

*Source: System Overview, page None*


**ASSERTION** (confidence: 90%)

> 40% of transaction processing migrated to Kubernetes cluster

*Source: System Overview, page None*


**ASSERTION** (confidence: 95%)

> Transaction routing logic is not fully documented

*Source: System Overview, page None*


**ASSERTION** (confidence: 90%)

> Operations team manually overrides routing rules during peak periods

*Source: System Overview, page None*


**ASSERTION** (confidence: 95%)

> Customer authentication uses BankID (Swedish), BankID (Norwegian), and FTN

*Source: Authentication, page None*


**ASSERTION** (confidence: 95%)

> Internal staff authenticate via Azure AD with SAML 2.0 federation

*Source: Authentication, page None*


**ASSERTION** (confidence: 95%)

> MFA implemented for all administrative access in Q1 2024

*Source: Authentication, page None*


**PLAN** (confidence: 90%)

> MFA enforcement for service accounts delayed to Q1 2025

*Source: Authentication, page None*


**ASSERTION** (confidence: 95%)

> 47 service accounts still use password-only authentication

*Source: Authentication, page None*


**ASSERTION** (confidence: 90%)

> Risk acceptance signed by CISO with 6-month remediation window

*Source: Authentication, page None*


**ASSERTION** (confidence: 95%)

> Break-glass used 14 times in past quarter

*Source: Authentication, page None*


**ASSERTION** (confidence: 95%)

> Only 6 post-incident reviews completed out of 14 break-glass uses

*Source: Authentication, page None*


**REQUIREMENT** (confidence: 95%)

> Post-incident review required within 72 hours per policy SEC-AM-003

*Source: Authentication, page None*


**PLAN** (confidence: 85%)

> Old LDAP directory scheduled for decommission

*Source: Authentication, page None*


**ASSERTION** (confidence: 85%)

> 200-300 users still depend on LDAP system

*Source: Authentication, page None*


**ASSERTION** (confidence: 90%)

> LDAP decommission originally planned for June 2024

*Source: Authentication, page None*


**ASSERTION** (confidence: 95%)

> All customer PII encrypted at rest using AES-256-GCM

*Source: Data Protection, page None*


**ASSERTION** (confidence: 95%)

> Encryption keys managed through Thales Luna Network HSM 7

*Source: Data Protection, page None*


**REQUIREMENT** (confidence: 95%)

> Key rotation occurs every 12 months per PCI-DSS requirements

*Source: Data Protection, page None*


**ASSERTION** (confidence: 95%)

> CUSTOMER_LEGACY table containing 340,000 migrated records stored unencrypted

*Source: Data Protection, page None*


**ASSERTION** (confidence: 90%)

> CUSTOMER_LEGACY table shows 50-100 queries daily from reporting module

*Source: Data Protection, page None*


**ASSERTION** (confidence: 85%)

> DBA team claims CUSTOMER_LEGACY table is not in active use

*Source: Data Protection, page None*



---

## Entities (0)


---

## Extraction Metadata

- **Model:** claude-sonnet-4-20250514
- **Date:** 2026-01-30T18:45:27.849516
- **Documents:** 1
- **Truths:** 24
- **Entities:** 0
- **Relationships:** 0