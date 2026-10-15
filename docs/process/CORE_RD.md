# Core R&D and continuous improvement

Covers LA-RD-01, LA-RD-02, LA-RD-03 and LA-RD-05 (PRD section 7.3). Core R&D is a process, not a running component.

- **Independent function (LA-RD-01).** Core R&D evaluates and improves the Dyson Core: model routing, safety, runtime, performance, capabilities and future possibilities.
- **Proposals only (LA-RD-02).** Its output is researched proposals. It never makes an automatic constitutional change. It has no write access to `policy/` and cannot approve anything.
- **Separate from Layer B (LA-RD-03).** It stays separate from the Layer B Receptor Genesis Engine. Its work lives in `docs/rd/` and never in `receptors/`.
- **Advisory external reviews (LA-RD-05).** External reviews, for example by Claude or Gemini, are advisory. They remain subject to the data and permission rules: no secrets, no Receptor-private data, and redaction once gate 6 defines it.
- **Through the amendment workflow (LA-RD-04, proven in Step 9).** A proposal enters the Governed Amendment Workflow (PRD 7.4) like any other.

## How a proposal moves

1. Write it in `docs/rd/` with rationale, dependencies, risk and cost.
2. Open it as a pull request labelled `rd-proposal`. Review is advisory.
3. Anything that touches `policy/` follows the amendment workflow and needs the Founder's explicit, authenticated approval of the exact diff. A change to AMD-1 to AMD-13 also changes `policy/amd_register.lock`, so CI makes it visible.
