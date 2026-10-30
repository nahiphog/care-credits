# Backend reconciliation

Based on dman1313/CareCredits main b7e8765 and deployed nahiphog/care-credits 27350e5.

The refactor imported Candidate, DigestPreference and SCHEMA_VERSION from modules that did not define them, while security still imported the removed portal_models module. Its account model omitted name, role and session/profile fields required by the live API; its course model omitted persisted data/evidence fields. Enabling it directly against production would break sessions and catalogue operations.

Resolution:

- Retain router/service organization with five domain routers and a single shared application service implementation.
- Restore the complete production schema v17 under models/schema.py. Legacy imports alias that module rather than creating a second SQLAlchemy registry.
- Keep all 47 production endpoints, exact request/response signatures, dependencies, origin checks, role checks, review validation, leases, audit trail, certificates, digests and suggestions.
- Retain the week-key pipeline introduced in #8; carry over live model receipts/configuration and the review-only serverless completion fix.
- Replace incomplete repository/service fragments with the proven catalogue, digest, schedule, certificate and portal services. Bulk auto-approve routes from the incomplete refactor are not exposed: they bypassed the evidence/version-aware review contract. The supported operator review path publishes valid candidates and records the decision.
- Preserve the existing Neon schema and data; no migration, reset or reseeding.
- Move the frontend and Vercel configuration to the root and remove both the staging deployment copy and outdated frontend copy.

The application service remains a large module; further splitting it into smaller services is an internal cleanup, not a second backend or prerequisite to using this app.

Production stays on the existing daily-gattai/care-credits Vercel project and care-credits-hackathon.vercel.app domain. The production Git source remains nahiphog/care-credits, branch codex/v1-integrated-demo, with Root Directory unset (repository root). The integration PR in dman1313/CareCredits remains open for review. Keep all existing private environment variables and the Neon integration.
