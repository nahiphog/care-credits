# Judge walkthrough

Care Credits brings Malaysian CPD discovery, provider evidence and a doctor's personal learning record into one application. The intended outcome is less time searching and organising training, with a clear distinction between provider claims and self-reported attendance.

**[Open the live application](https://care-credits-hackathon.vercel.app/) · [Application source](https://github.com/nahiphog/care-credits/tree/codex/v1-integrated-demo) · [Setup](SETUP.md)**

## Choose a route

| Route | What it demonstrates | Access |
| --- | --- | --- |
| Public application | Deployed catalogue, real provider links and personal tracking | Create your own doctor account; use a private password |
| Local fictional demo | Repeatable doctor and operator flows, including review and publication | Follow [setup](SETUP.md); public local-only credentials below |
| Recorded live extraction evidence | Actual NVIDIA inference on Nebius, separate from fixtures | Read the receipt summary below and [release validation](RELEASE_VALIDATION.md) |

The public app does not accept the demo credentials. Production operator access is restricted; use the local operator account to evaluate those controls without needing the owner's account. Email recovery is disabled, so retain your password if registering on the public app.

## Local walkthrough: about five minutes after setup

Use the frontend URL printed by `scripts/dev.py --demo`. The steps below deliberately avoid paid discovery and real registrations. Both local passwords are `CareCredits-demo-2026`.

### 1. Find a course as a doctor

1. Sign in as `doctor@carecredits.local` using **Sign in and search**.
2. Search for **Diabetes care in general practice**.
3. Open its result and inspect the course details.

Expected: one fictional listing from **Primary Care Learning Lab**, in **Kuala Lumpur**, with a **MYR 180** fee and **4 advertised CPD points**. The scheduled date is twelve days after the demo seed date. The detail view labels it as a demo/unverified course and explains that provider registration happens externally. Its `example.org` links are placeholders; they are not real course bookings.

Open **Filters** to inspect the modal, then **Cancel** to leave the search unchanged. Clear the search and filters to return to all published examples.

### 2. Save a personal learning record

1. Search for **Communication in primary care**, a past fictional course.
2. Open it and set provider sign-up and attendance in **Your personal record**. Use the displayed course date as the attendance date, record **2** self-reported CPD points, and save.
3. Reload the page, reopen the course and confirm the record persists.
4. Open **Overview** to review the learning total. Open **My Credits** and choose **Export CSV** for the selected year.

Expected: the new attendance is included in your personal record and CSV. On a fresh seed when both attended course dates fall in the selected year, the original 3 points plus this record produce **5 self-reported points**. At a year boundary, select the attendance year rather than expecting that fixed total. Future courses should not be marked attended early.

Demo credential sign-in refreshes seeded examples, so use a page reload for the persistence check rather than signing out and back in. These totals are not regulatory credit approval or proof of annual renewal eligibility.

### 3. Print an affiliation record

1. Open **Certificates**.
2. Choose **Issue affiliation record** for the selected year.
3. Open the new **Open / print** link and inspect the document.

Expected: a saved Care Credits affiliation record for **Dr Daniel Tan**, with history retained after reload. It is explicitly not an MMC, MOH or APC certificate. Printing is optional; merely opening the document is sufficient to evaluate it.

### 4. Review and publish as an operator

1. Sign out, then sign in as `demo@carecredits.local`.
2. Open **Discover** or **Overview** in the main dashboard. Operator discovery and review tools appear alongside the catalogue.
3. Find the **Fixture review queue** and open a pending candidate such as **Asthma updates for GPs (demo)**.
4. Inspect its captured source text and field evidence. The text explicitly identifies a fictional demonstration source.
5. Publish the candidate using the review controls. Return to the dashboard and search its exact title.

Expected: the review succeeds and exactly one published listing appears in search. A previously published candidate should not create a second listing. If this demo database has already been used, choose another pending fixture or start with a fresh demo checkout; do not assume a published item is still pending.

This proves the review → publication → search path with local data. It is **not** a live Tavily/NVIDIA run or evidence that a real course is accredited. Do not launch paid discovery for this key-free walkthrough.

### 5. Inspect operational controls

In the dashboard's operator discovery panel, expand **Advanced tools & connection details**, then **Maintenance and catalogue quality** and use **Refresh checks**.

Expected: the operator can inspect catalogue-quality findings and maintenance information. A newly created local database may have no maintenance receipt; missing live integrations are expected without credentials. A doctor account does not gain operator actions merely by opening `/workspace`.

## NVIDIA / Nebius evidence

The live pipeline uses **Tavily** to retrieve source pages and **`nvidia/nemotron-3-super-120b-a12b` on Nebius Token Factory** to extract structured course candidates. Backend schema and source-evidence checks run before a candidate enters review; publication also checks for an existing course/session identity.

| Receipt field | Recorded value |
| --- | --- |
| Verification date | 30 October 2026 |
| Job ID | `541b975e26994f5f8c6feb1621390886` |
| Model ID | `nvidia/nemotron-3-super-120b-a12b` |
| Model endpoint host | `api.tokenfactory.nebius.com` |
| Reported model tokens | 5,401 |
| Validated candidates | 4 |
| Result | Succeeded, no warnings; terminal replay returned the stored receipt |

See [release validation](RELEASE_VALIDATION.md#extraction-repair-and-successful-live-verification--30-october-2026), [deployment evidence](VERCEL.md), and [model provenance links](../shared/model_defaults.py). The live run selected a provider homepage; it does not independently prove every fallback-fetch path. Four candidates does not mean four new published courses. Publication requires its own evidence and duplicate review.

The fixture workflow makes no model call. A model name displayed in settings, readiness alone, or a search returning no pages is not proof of inference. An operator with privately configured keys can reproduce a live run, but that consumes provider credits and is not required for the local walkthrough. Never share production operator passwords or API keys with the submission.

## Evaluation checklist

- [ ] I opened the integrated application branch, not the older `main` starter.
- [ ] I could start the local demo using the setup instructions without API keys.
- [ ] The exact diabetes search returned the expected fictional course and source labels.
- [ ] A saved attendance record survived reload and appeared in personal tracking/CSV.
- [ ] An affiliation record could be opened and was not presented as regulator certification.
- [ ] An operator could review fixture evidence and publish a single searchable listing.
- [ ] Doctor access did not expose operator publication controls.
- [ ] I could distinguish recorded live NVIDIA/Nebius evidence from the offline demo.

The [local verification record](LOCAL_DEMO_VERIFICATION.md) states which steps were actually rehearsed. [Operational limits](OPERATIONS.md) cover bounded discovery, free-plan quotas, disabled email, maintenance and recovery. This is a working pilot, not a guarantee of course accreditation, automatic provider registration or professional licence renewal.
