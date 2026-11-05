# Security

Paper trading is the only supported mode. Enabling live mode must fail at startup. Never connect a funded wallet. Public Polymarket data access needs no private keys. Keep .env and local databases out of Git. The API binds to loopback; deployment requires separate authentication, TLS, review and authorization. Dependency audits run in CI; report vulnerabilities privately to repository owners. No pooled capital or eligibility claims are made.
