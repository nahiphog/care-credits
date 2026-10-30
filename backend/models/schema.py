"""Passive model compatibility exports; canonical mappings live by domain."""
from .common import uid, SCHEMA_VERSION, CANDIDATE_SCHEMA_VERSION
from .account import Account
from .profile import AccountProfile
from .course import Course, SourceDocument, FieldEvidence
from .record import Record, RecordHistory
from .ingestion import Job, Candidate
from .audit import Audit, Throttle
from .digest import DigestPreference, DigestSend
from .certificate import AffiliationCertificate
from .session import LoginSession
from .schema_version import SchemaVersion
from .operations import PasswordReset, MaintenanceRun, DigestDispatch
