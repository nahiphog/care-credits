"""Explicit fictional fixtures. Loaded only with DEMO_MODE=true outside production."""
from datetime import timedelta
from portal_models import Account, Candidate, Course, Job, Record, fill_course
from security import password_hash
from shared.contracts import Training

DEMO_PASSWORD = 'CareCredits-demo-2026'
DEMO_EMAILS = ('demo@carecredits.local', 'doctor@carecredits.local')


REVIEW_QUOTE_TEMPLATE = (
    'Fictional demo CME: {title} by Demo CME Network in Malaysia Kuala Lumpur online. '
    '{start_date}. CPD points 3. Fee MYR 120. Register at {registration_url}. '
    'Demonstration source only — not a live Tavily or model result.'
)


def _candidate_payload(title, start_date, source_key_suffix):
    start = str(start_date)
    registration = 'https://example.org/carecredits-demo-candidate-' + source_key_suffix + '/register'
    source_url = 'https://example.org/carecredits-demo-candidate-' + source_key_suffix
    quote = REVIEW_QUOTE_TEMPLATE.format(title=title, start_date=start, registration_url=registration)
    evidence_fields = (
        'title',
        'provider',
        'mode',
        'country',
        'start_date',
        'city',
        'points',
        'credit_label',
        'difficulty',
        'fee',
        'currency',
        'registration_url',
    )
    training = Training(
        title=title,
        provider='Demo CME Network',
        description='Fictional candidate for operator review rehearsal. Not a live discovery result.',
        start_date=start_date,
        city='Kuala Lumpur',
        mode='online',
        country='MY',
        points=3,
        credit_label='CPD',
        difficulty='intermediate',
        fee=120,
        currency='MYR',
        source_url=source_url,
        registration_url=registration,
        source_text=quote,
        evidence={key: quote for key in evidence_fields},
    )
    return training.model_dump(mode='json')


def seed(db):
    from main import today

    demo_hash = password_hash(DEMO_PASSWORD)
    for email, name, role in [
        (DEMO_EMAILS[0], 'Dr Aisha Rahman', 'operator'),
        (DEMO_EMAILS[1], 'Dr Daniel Tan', 'doctor'),
    ]:
        existing = db.query(Account).filter_by(email=email).first()
        if existing:
            existing.password_hash = demo_hash
            existing.name = name
            existing.role = role
        else:
            db.add(
                Account(
                    email=email,
                    name=name,
                    role=role,
                    password_hash=demo_hash,
                    bio='General practitioner · committed to continuing professional development.',
                )
            )
    db.flush()
    operator = db.query(Account).filter_by(email='demo@carecredits.local').one()
    doctor = db.query(Account).filter_by(email='doctor@carecredits.local').one()

    items = [
        ('Diabetes care in general practice', 'Primary Care Learning Lab', 12, 'Kuala Lumpur', 'in_person', 180, 4, 'intermediate', 3.139, 101.687),
        ('Everyday dermatology for GPs', 'Community Medicine Academy', 21, 'Petaling Jaya', 'hybrid', 250, 6, 'beginner', 3.107, 101.606),
        ('ECG essentials: a practical refresher', 'Clinical Skills Collective', 8, None, 'online', 0, 2, 'beginner', None, None),
        ('A better approach to hypertension', 'Primary Care Learning Lab', -10, 'Kuala Lumpur', 'in_person', 150, 3, 'intermediate', 3.15, 101.71),
        ('Communication in primary care', 'Community Medicine Academy', -30, None, 'online', 80, 2, 'beginner', None, None),
        ('Preventive care across the lifespan', 'Clinical Skills Collective', 35, 'Shah Alam', 'in_person', None, None, None, 3.074, 101.518),
    ]
    course_ids = {}
    for i, (title, provider, offset, city, mode, fee, points, difficulty, lat, lon) in enumerate(items):
        key = 'demo-' + str(i)
        registration = 'https://example.org/carecredits-demo-' + str(i) + '/register'
        training = Training(
            title=title,
            provider=provider,
            description='Fictional demonstration training for testing the CareCredits workflow. This is not a real course or accreditation claim.',
            start_date=today() + timedelta(days=offset),
            city=city,
            state='Selangor' if city and city != 'Kuala Lumpur' else None,
            mode=mode,
            latitude=lat,
            longitude=lon,
            fee=fee,
            currency='MYR' if fee is not None else None,
            points=points,
            credit_label='CPD' if points is not None else None,
            difficulty=difficulty,
            prerequisites='For demonstration purposes only',
            source_url='https://example.org/carecredits-demo-' + str(i),
            registration_url=registration,
        )
        payload = training.model_dump(mode='json')
        existing = db.query(Course).filter_by(source_key=key).first()
        if existing:
            # Keep demo IDs stable while refreshing labelled registration links for DEMO-01 step 6.
            fill_course(existing, {**(existing.data or {}), **payload, 'registration_url': registration}, demo=True)
            # Operator cancel rehearsal must not leave demo-* sessions hidden after DEMO_MODE reseed.
            existing.publication_status = 'published'
            existing.cancellation_status = 'active'
            course_ids[i] = existing.id
            continue
        course = fill_course(Course(source_key=key), payload, demo=True)
        db.add(course)
        db.flush()
        course_ids[i] = course.id

    # Offline DEMO-01 steps 3–4: pending labelled candidates for /live review (no Tavily/model).
    fixture_result = {
        'extraction_status': 'fixture',
        'candidate_count': 3,
        'warnings': [
            'FIXTURE: fictional demo candidates for offline review. Not a Tavily Search/Extract or model run.',
        ],
        'sources': [
            {
                'url': 'https://example.org/carecredits-demo-candidate-asthma',
                'title': 'Asthma updates for GPs (demo)',
                'snippet': 'Demonstration source only — not a live Tavily or model result.',
                'extraction_status': 'fixture',
                'verification_status': 'unverified',
                'retrieved_at': 'fixture',
            },
            {
                'url': 'https://example.org/carecredits-demo-candidate-vaccine',
                'title': 'Adult vaccination clinic skills (demo)',
                'snippet': 'Demonstration source only — not a live Tavily or model result.',
                'extraction_status': 'fixture',
                'verification_status': 'unverified',
                'retrieved_at': 'fixture',
            },
            # Steady-state queue slot (after asthma/vaccine publish) needs job-source provenance too.
            {
                'url': 'https://example.org/carecredits-demo-candidate-queue',
                'title': 'Offline review queue (demo)',
                'snippet': 'Demonstration source only — not a live Tavily or model result.',
                'extraction_status': 'fixture',
                'verification_status': 'unverified',
                'retrieved_at': 'fixture',
            },
        ],
        'usage': {'tavily_credits': None, 'model_tokens': None},
    }
    job = db.query(Job).filter_by(request_key='demo-review-queue').first()
    if not job:
        job = Job(
            account_id=operator.id,
            request_key='demo-review-queue',
            query='Demo review queue (fictional fixtures)',
            status='succeeded',
            max_results=3,
            result=fixture_result,
        )
        db.add(job)
        db.flush()
    else:
        job.result = fixture_result
        job.status = 'succeeded'
        job.query = 'Demo review queue (fictional fixtures)'
        job.max_results = 3
    # Terminal fixture job must not look leased (parity with job-complete lease-clear).
    job.lease_token = None
    job.lease_until = None
    job.started_at = None
    # Keep offline review fixtures publishable: refresh evidence when DEMO_MODE reseeds.
    # Include demo-candidate-queue so a steady-state pending/held slot is not left with stale
    # evidence after asthma/vaccine are published (reviewable >= 1 skips the create block below).
    for title, suffix, offset in (
        ('Asthma updates for GPs (demo)', 'asthma', 40),
        ('Adult vaccination clinic skills (demo)', 'vaccine', 55),
        ('Offline review queue (demo)', 'queue', 70),
    ):
        payload = _candidate_payload(title, str(today() + timedelta(days=offset)), suffix)
        payload['_fixture'] = True
        # Match fixture job sources so DISC-03 review UI can show retrieval provenance offline.
        payload['retrieved_at'] = 'fixture'
        existing = db.query(Candidate).filter_by(source_key='demo-candidate-' + suffix).first()
        if existing:
            # Refresh offline review fixtures so DEMO_MODE login reseed keeps a publishable queue.
            # Published fixtures stay published (already in the catalogue); rejected reopen as pending.
            if existing.status in ('pending', 'held', 'rejected'):
                existing.data = payload
                existing.job_id = job.id
                if existing.status == 'rejected':
                    existing.status = 'pending'
                    existing.review_reason = ''
                    existing.reviewed_by = None
                    existing.reviewed_at = None
                # Bump version so operator CandidateCard remounts (id+version) after evidence refresh.
                existing.version = int(existing.version or 1) + 1
        elif suffix != 'queue':
            # Queue slot is created only when asthma/vaccine leave no reviewable row (below).
            db.add(
                Candidate(
                    job_id=job.id,
                    source_key='demo-candidate-' + suffix,
                    data=payload,
                    status='pending',
                )
            )

    # Offline publish → cancel rehearsal: re-list catalogue sessions owned by published fixture candidates
    # (identity is not demo-*; demo-* re-list above does not cover them).
    for published in (
        db.query(Candidate)
        .filter(
            Candidate.source_key.like('demo-candidate-%'),
            Candidate.status == 'published',
        )
        .all()
    ):
        course_id = published.resulting_course_id
        if not course_id:
            continue
        published_course = db.get(Course, course_id)
        if not published_course:
            continue
        published_course.publication_status = 'published'
        published_course.cancellation_status = 'active'
        published_course.demo = True

    # If both asthma/vaccine were published, keep a dedicated pending slot so Fixture review stays rehearsable.
    reviewable = (
        db.query(Candidate)
        .filter(
            Candidate.source_key.like('demo-candidate-%'),
            Candidate.status.in_(('pending', 'held')),
        )
        .count()
    )
    if reviewable == 0:
        from catalogue import exact_course, source_key as course_source_key

        queue_payload = _candidate_payload(
            'Offline review queue (demo)',
            str(today() + timedelta(days=70)),
            'queue',
        )
        queue_payload['_fixture'] = True
        queue_payload['retrieved_at'] = 'fixture'
        queue = db.query(Candidate).filter_by(source_key='demo-candidate-queue').first()
        if queue:
            queue.data = queue_payload
            queue.job_id = job.id
            # Force pending even if a prior reseed published this rehearsal slot.
            prior_course_id = queue.resulting_course_id
            queue.status = 'pending'
            queue.review_reason = ''
            queue.reviewed_by = None
            queue.reviewed_at = None
            queue.resulting_course_id = None
            # Cancel the rehearsal catalogue row (linked and/or same identity). Clearing the
            # candidate link alone orphaned a published listing and 409'd the next publish.
            linked = db.get(Course, prior_course_id) if prior_course_id else None
            twin = exact_course(db, course_source_key(queue_payload))
            for row in {row.id: row for row in (linked, twin) if row}.values():
                row.publication_status = 'cancelled'
                row.cancellation_status = 'cancelled'
                row.demo = True
            queue.version = int(queue.version or 1) + 1
        else:
            db.add(
                Candidate(
                    job_id=job.id,
                    source_key='demo-candidate-queue',
                    data=queue_payload,
                    status='pending',
                )
            )

    # Offline DEMO-01 step 7: personal records on both documented accounts (operator for /live review flow,
    # doctor for a pure doctor login). Reseed restores fixture tracking after cancel/edit rehearsal.
    past = today() + timedelta(days=-10)

    def _restore_demo_record(account_id, course_id, **fields):
        existing = db.query(Record).filter_by(account_id=account_id, course_id=course_id).first()
        if not existing:
            db.add(Record(account_id=account_id, course_id=course_id, **fields))
            return
        changed = False
        for key, value in fields.items():
            if getattr(existing, key) != value:
                setattr(existing, key, value)
                changed = True
        if changed:
            existing.version = int(existing.version or 0) + 1

    for account in (operator, doctor):
        if 2 in course_ids:
            _restore_demo_record(
                account.id,
                course_ids[2],
                signed_up=True,
                signup_status='signed_up',
                attendance_status='not_recorded',
                attended=False,
                attended_on=None,
                points=None,
                credit_label='CPD',
                points_origin='',
                public=False,
                notes='',
            )
        if 3 in course_ids:
            _restore_demo_record(
                account.id,
                course_ids[3],
                signed_up=True,
                signup_status='signed_up',
                attended=True,
                attendance_status='attended',
                attended_on=past.isoformat(),
                points=3,
                credit_label='CPD',
                points_origin='self_reported',
                public=False,
                notes='',
            )
    db.commit()
