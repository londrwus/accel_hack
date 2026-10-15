# Responsible design

15% of the score. **Show it in the product**, not only in this doc.

## Risks and what we do about them

| Risk | Mitigation | Where it's visible |
|---|---|---|
| **Hallucinated facts** in a memo that drives a money decision | Every claim needs a source (URL or dataset row). The Critic agent checks each claim and marks unsupported ones. Unsupported claims are shown struck through or amber, never hidden. | Memo → Trust strip, claim badges |
| **Automation without oversight** | Bellwether only recommends. Approve/Pass is a human action. No auto-outreach, no emails to founders, no commitments. | "Human decision required" on the memo |
| **Bias** (e.g. favouring one geography, ignoring under-represented founders) | We never use or infer founder gender, age, ethnicity or nationality. A shortlist mix (sector/geo) is shown so skew is visible. Score contributions are explainable. | Shortlist "mix" chip, score breakdown |
| **Privacy** | Public company information only. No scraping of personal social profiles. Founders appear by public role and name only. Data stays in local SQLite and can be deleted per fund. | Footer: "Public sources only · Delete fund data" |
| **Prompt injection from scraped web pages** | Web content is wrapped as untrusted data, and instructions found inside pages are ignored. Tool permissions are scoped (agents can read the web but can't send anything out). | Event `warning: ignored instructions found on page` |
| **Misuse** (competitive intelligence against a fund, harassment, mass scraping) | Respect robots.txt, rate limits, a page cap per run, no bulk export of people data, and an audit log of every run. | Run log |
| **Over-trust in scores** | Show a confidence level and "what we couldn't verify". The score is labelled "fit with this fund's past behaviour", not "will succeed". | Memo header |
| **Conflicts of interest** | Flag when a predicted deal competes with an existing portfolio company. | Red edge on the Market Map + memo flag |

## The one-line version for the pitch

"Bellwether cites everything, a second agent checks its work, it never uses founders' personal traits, and a human always makes the call."

Not investment advice: the memo footer says so.
