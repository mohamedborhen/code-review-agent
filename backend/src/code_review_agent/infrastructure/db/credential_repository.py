"""Credential vault - Fernet encrypt/decrypt helpers for RepoCredential.

PHASE_5_FRONTEND.md §3/§4, FINAL Compliance: credentials are write-only,
encrypted server-side with Fernet(CREDENTIAL_ENCRYPTION_KEY), never returned,
never logged, never written to .git/config or browser storage.
"""

import logging

from cryptography.fernet import Fernet
from sqlmodel import Session, select

from infrastructure.config import settings
from infrastructure.db.engine import engine
from infrastructure.db.models import RepoCredential

logger = logging.getLogger(__name__)


_EPHEMERAL_KEY: bytes | None = None


def _fernet() -> Fernet:
    """Return a Fernet instance from the configured encryption key.

    If CREDENTIAL_ENCRYPTION_KEY is not set (dev/test), an ephemeral key is
    generated once per process and reused — vault rows won't survive restart.
    """
    global _EPHEMERAL_KEY
    key = settings.credential_encryption_key
    if key is None:
        if _EPHEMERAL_KEY is None:
            _EPHEMERAL_KEY = Fernet.generate_key()
            logger.warning("CREDENTIAL_ENCRYPTION_KEY not set — using ephemeral Fernet key (vault not persistent)")
        return Fernet(_EPHEMERAL_KEY)
    if isinstance(key, str):
        key = key.encode("utf-8")
    return Fernet(key)


def _encrypt(plaintext: str | None) -> bytes | None:
    """Encrypt a plaintext string to a Fernet ciphertext blob."""
    if plaintext is None:
        return None
    return _fernet().encrypt(plaintext.encode("utf-8"))


def _decrypt(ciphertext: bytes | None) -> str | None:
    """Decrypt a Fernet ciphertext blob to plaintext string.

    Never logs the plaintext. On decryption failure, logs the error and
    returns None rather than propagating (vault reads are best-effort).
    """
    if ciphertext is None:
        return None
    try:
        return _fernet().decrypt(ciphertext).decode("utf-8")
    except Exception:
        logger.error("Fernet decryption failed - corrupt or wrong-key ciphertext")
        return None


class CredentialRepository:
    """Repository for per-repo encrypted credential vault operations.

    All methods accept and return plain strings. Encryption/decryption
    happens inside this class - callers never see ciphertext.
    """

    def store(
        self,
        repo_id: str,
        user_id: str,
        repo_url: str | None = None,
        github_pat: str | None = None,
        webhook_secret: str | None = None,
        jira_url: str | None = None,
        jira_email: str | None = None,
        jira_api_token: str | None = None,
    ) -> RepoCredential:
        """Store or upsert encrypted credentials for a repo.

        Called from POST /api/v1/repos after validation. The repo_url is
        stored encrypted here so re-clone after eviction is possible.
        """
        with Session(engine) as session:
            existing = session.exec(
                select(RepoCredential).where(RepoCredential.repo_id == repo_id)
            ).first()

            if existing:
                # Update in place - same user_id ownership enforced upstream
                enc_url = _encrypt(repo_url)
                if enc_url is not None:
                    existing.repo_url_encrypted = enc_url
                enc_pat = _encrypt(github_pat)
                if enc_pat is not None:
                    existing.github_pat_encrypted = enc_pat
                enc_wh = _encrypt(webhook_secret)
                if enc_wh is not None:
                    existing.webhook_secret_encrypted = enc_wh
                if jira_url is not None:
                    existing.jira_url = jira_url
                if jira_email is not None:
                    existing.jira_email = jira_email
                enc_jira = _encrypt(jira_api_token)
                if enc_jira is not None:
                    existing.jira_api_token_encrypted = enc_jira
                session.add(existing)
                session.commit()
                session.refresh(existing)
                return existing

            cred = RepoCredential(
                repo_id=repo_id,
                owning_user_id=user_id,
                repo_url_encrypted=_encrypt(repo_url),
                github_pat_encrypted=_encrypt(github_pat),
                webhook_secret_encrypted=_encrypt(webhook_secret),
                jira_url=jira_url,
                jira_email=jira_email,
                jira_api_token_encrypted=_encrypt(jira_api_token),
            )
            session.add(cred)
            session.commit()
            session.refresh(cred)
            return cred

    def get_repo_url(self, repo_id: str) -> str | None:
        """Return the decrypted repo_url for a repo, or None if not stored."""
        with Session(engine) as session:
            cred = session.exec(
                select(RepoCredential).where(RepoCredential.repo_id == repo_id)
            ).first()
            if cred is None:
                return None
            return _decrypt(cred.repo_url_encrypted)

    def get_pat(self, repo_id: str) -> str | None:
        """Return the decrypted GitHub PAT for a repo, or None."""
        with Session(engine) as session:
            cred = session.exec(
                select(RepoCredential).where(RepoCredential.repo_id == repo_id)
            ).first()
            if cred is None:
                return None
            return _decrypt(cred.github_pat_encrypted)

    def get_webhook_secret(self, repo_id: str) -> str | None:
        """Return the decrypted webhook HMAC secret for a repo, or None."""
        with Session(engine) as session:
            cred = session.exec(
                select(RepoCredential).where(RepoCredential.repo_id == repo_id)
            ).first()
            if cred is None:
                return None
            return _decrypt(cred.webhook_secret_encrypted)

    def get_jira_credentials(self, repo_id: str) -> dict | None:
        """Return decrypted Jira credentials for a repo, or None.

        Returns a dict with keys: jira_url, jira_email, jira_api_token.
        None if no vault row or no Jira credentials stored.
        """
        with Session(engine) as session:
            cred = session.exec(
                select(RepoCredential).where(RepoCredential.repo_id == repo_id)
            ).first()
            if cred is None:
                return None
            token = _decrypt(cred.jira_api_token_encrypted)
            if cred.jira_url is None and cred.jira_email is None and token is None:
                return None
            return {
                "jira_url": cred.jira_url,
                "jira_email": cred.jira_email,
                "jira_api_token": token,
            }

    def get_by_repo_id(self, repo_id: str) -> dict | None:
        """Return ownership dict for a repo, or None if not found.

        Returns {owning_user_id: str, repo_id: str}. Used for 409 hijack check.
        Does NOT return credential ciphertext.
        """
        with Session(engine) as session:
            cred = session.exec(
                select(RepoCredential).where(RepoCredential.repo_id == repo_id)
            ).first()
            if cred is None:
                return None
            return {"owning_user_id": cred.owning_user_id, "repo_id": cred.repo_id}

    def get_all_by_user(self, user_id: str) -> list[dict]:
        """Return list of {repo_id} for all repos owned by a user.

        Does NOT return any credential data - used for repo listing only.
        """
        with Session(engine) as session:
            creds = session.exec(
                select(RepoCredential).where(RepoCredential.owning_user_id == user_id)
            ).all()
            return [{"repo_id": c.repo_id} for c in creds]
