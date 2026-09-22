# ADR: focused security hardening

Status: implemented and deployed locally on 22 September 2026; AWS deployment pending. Migration `0016`, local readiness, authorized audit access, runtime grants and preservation of existing values across 33 tables were verified. See implementation status for backups and deployment details.

## Security by Architecture

Adopt centralized per-clinic role filtering, deterministic policy rechecks, minimum-necessary model observations, strict in-memory Bridge parsing and an audit projection over existing evidence. Preserve the API-versus-Bridge ownership contract and all existing patient-follow-up semantics. The detailed controls, role matrix, limitations, migration and future-production boundary are in [Security by Architecture](SECURITY_ARCHITECTURE.md).

Migration `0016` preserves existing membership authority as `staff` and adds a security-event ledger. Unknown roles fail closed. Staff and admin share the current staff-action permission set; auditor is read-only; viewer sees masked summaries. No new product workflow or appointment engine is introduced.

Use existing agent events, policy decisions, source receipts and notification ledgers rather than duplicating them. Add transactional audit entries only where Bridge review/approval and option changes or retry requests previously lacked durable actor/change history. Denials are recorded after the rejected request transaction has ended, so rollback does not discard them. Do not claim historical evidence that was not originally captured.

## Future Production Hardening — NOT YET IMPLEMENTED

Secrets Manager/SSM, verified encryption/KMS and backups, MFA and stronger sessions, WAF/shared rate limits, centralized monitoring/alerts, retention/deletion, malware/content scanning, secure backup/restore exercises, incident response/breach procedures, dependency scanning, penetration testing and organizational Singapore PDPA/healthcare controls remain future work. See the full list and implementation limits in the security reference.
