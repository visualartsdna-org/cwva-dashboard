"""Making a `vad:ProofEvent` without anyone transcribing a value.

Three parts, deliberately separated (`PROOF_WORKFLOW.md`):

- `merkle` — the arithmetic and the packed storage form. Durable: it does not
  care where a path came from.
- `certificate` — reading an OriginStamp certificate PDF, stdlib only.
  Disposable: an API adapter replaces this file and nothing else.
- `validate` — the three gates. What makes any adapter trustworthy.

The division is the design. Every defect in the twenty-four records made by
hand came from a human reading a value off a page; the gates exist so that a
machine reading it wrongly cannot write the mistake into a record that claims
to be evidence.
"""

from .certificate import Certificate, CertificateError, read_certificate
from .merkle import Step, combine, fold, pack, reconstruct, unpack, verify
from .validate import ProofFields, Validation, validate

__all__ = [
    "Certificate", "CertificateError", "read_certificate",
    "Step", "combine", "fold", "pack", "unpack", "verify", "reconstruct",
    "ProofFields", "Validation", "validate",
]
