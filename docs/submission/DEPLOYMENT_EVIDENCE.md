# Deployment evidence

**Project:** Forget-lah | **Team:** SP-ARK Agents | **Code:** N63VHYEX

## Documented hosted demonstration

URL: https://forget-lah.52-220-111-31.sslip.io

The repository records an AWS Lightsail deployment in Singapore (`ap-southeast-1`) with HTTPS, a staff dashboard, application API, durable worker, PostgreSQL and a separate synthetic Clinic System service. The demo requires authorised staff access. Credentials are not included in Git; arrange reviewer access with the submitting team.

The URL and checks below are recorded evidence, not a guarantee of current uptime or a production availability SLA. The host is a single-host prototype; do not reset data or send patient messages merely to inspect the deployment.

## Evidence available to reviewers

| Record | Evidence and limits |
| --- | --- |
| [AWS deployment log](../AWS_DEMO.md) | Dated release, readiness, authentication, migration and preservation checks |
| [Organiser gateway](../ORGANISER_GATEWAY.md) | 25 September provider deployment, bounded synthetic live checks and private configuration handling |
| [Failure handling](../FAILURE_HANDLING.md) | Durable staff review and acknowledgement behaviour; recovery limitations |
| [Security architecture](../SECURITY_ARCHITECTURE.md) | Implemented boundary controls, audit and future production hardening |
| [GitHub checks](https://github.com/satworkz/forget-lah/actions/runs/36126040277) | Successful CI for merge commit `80a9b4f`; CI validates source, not live-host uptime |

The final submission video demonstrates the deployed product workflows with synthetic clinic records. A simulated clinic source is not a real clinical-system integration; a source receipt and notification delivery are separate evidence items.
