"""
drive_client.py — Google Drive upload/download for the Online mode.

Two ways to connect:

  1) DriveClientOAuth  (recommended for a normal personal Gmail)
       Uploads to YOUR OWN Drive using YOUR storage quota. First use opens a
       browser once to grant access; the token is cached afterwards.

  2) DriveClient  (Service Account)
       Good only with a Shared Drive (Google Workspace). A service account has
       NO storage quota of its own, so uploading to a personal My Drive folder
       fails with 'storageQuotaExceeded' — use OAuth instead in that case.

Dependencies: google-api-python-client, google-auth, google-auth-oauthlib
"""

from __future__ import annotations

import io
import os
import re

import requests
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload, MediaIoBaseDownload

# Full Drive scope: the owner uploads/shares/deletes, and an allowed recipient
# must be able to read a file that was SHARED with them (drive.file is not
# enough for that), so both roles use the full scope.
SCOPES_SA = ["https://www.googleapis.com/auth/drive"]
SCOPES_OAUTH = ["https://www.googleapis.com/auth/drive"]


class _DriveBase:
    """Shared upload/download/check; subclasses set self.service + self.folder_id."""
    service = None
    folder_id = ""

    def upload_bytes(self, data: bytes, name: str,
                     mime: str = "application/octet-stream") -> str:
        meta = {"name": name}
        if self.folder_id:
            meta["parents"] = [self.folder_id]
        media = MediaInMemoryUpload(data, mimetype=mime, resumable=False)
        f = self.service.files().create(
            body=meta, media_body=media, fields="id",
            supportsAllDrives=True).execute()
        return f["id"]

    def download_bytes(self, file_id: str) -> bytes:
        req = self.service.files().get_media(fileId=file_id, supportsAllDrives=True)
        buf = io.BytesIO()
        downloader = MediaIoBaseDownload(buf, req)
        done = False
        while not done:
            _status, done = downloader.next_chunk()
        return buf.getvalue()

    def make_public(self, file_id: str, role: str = "writer") -> None:
        """Let anyone with the link access the file. role='writer' lets a
        recipient DELETE it after a one-time decrypt (needs an authenticated
        Drive client to issue the delete)."""
        self.service.permissions().create(
            fileId=file_id, body={"type": "anyone", "role": role},
            supportsAllDrives=True).execute()

    def share_with_email(self, file_id: str, email: str,
                         role: str = "writer") -> None:
        """Grant access to ONE specific Google account (allow-list). role='writer'
        so the recipient can delete the file after a one-time decrypt."""
        self.service.permissions().create(
            fileId=file_id,
            body={"type": "user", "role": role, "emailAddress": email},
            sendNotificationEmail=False, supportsAllDrives=True).execute()

    def delete_file(self, file_id: str) -> bool:
        """Make an online file unusable after a one-time decrypt. Returns True if
        the data is gone.

        Google Drive reality: only the OWNER can delete or trash a My Drive file.
        A non-owner recipient (shared as writer) can do NEITHER — but a writer CAN
        overwrite the file's CONTENT. So if we can't delete, we destroy the
        encrypted payload by overwriting it with one harmless byte: the file
        object may linger (empty) until the owner removes it, but it can never be
        decrypted again. That is what 'one-time decrypt' actually needs."""
        # 1) owner path — delete permanently
        try:
            self.service.files().delete(
                fileId=file_id, supportsAllDrives=True).execute()
            return True
        except Exception:
            pass
        # 2) non-owner path — neutralize the content so re-decrypt is impossible
        try:
            media = MediaInMemoryUpload(b"\x00", mimetype="application/octet-stream",
                                        resumable=False)
            self.service.files().update(
                fileId=file_id, media_body=media,
                supportsAllDrives=True).execute()
            return True
        except Exception:
            pass
        # 3) last resort — try to trash it (works only if we happen to be owner)
        try:
            self.service.files().update(
                fileId=file_id, body={"trashed": True},
                supportsAllDrives=True).execute()
            return True
        except Exception:
            return False

    def check(self) -> str:
        about = self.service.about().get(fields="user(emailAddress)").execute()
        return about.get("user", {}).get("emailAddress", "(unknown)")


def public_download_bytes(file_id: str) -> bytes:
    """Download a file that is shared 'anyone with the link' — NO credentials
    needed, so a person with a different Gmail (or none) can fetch it.
    Handles Google's large-file 'confirm' interstitial."""
    sess = requests.Session()
    base = "https://drive.usercontent.google.com/download"
    r = sess.get(base, params={"id": file_id, "export": "download"}, stream=True)
    ctype = r.headers.get("Content-Type", "")
    if "text/html" not in ctype:
        return r.content
    # interstitial page -> pull the confirm token + uuid from the form and retry
    html = r.content
    confirm = re.search(rb'name="confirm"\s+value="([^"]+)"', html)
    uuid = re.search(rb'name="uuid"\s+value="([^"]+)"', html)
    params = {"id": file_id, "export": "download",
              "confirm": confirm.group(1).decode() if confirm else "t"}
    if uuid:
        params["uuid"] = uuid.group(1).decode()
    r = sess.get(base, params=params, stream=True)
    r.raise_for_status()
    return r.content


class DriveClient(_DriveBase):
    """Service-account client (needs a Shared Drive to actually store files)."""
    def __init__(self, service_account_json: str, folder_id: str = ""):
        creds = service_account.Credentials.from_service_account_file(
            service_account_json, scopes=SCOPES_SA)
        self.service = build("drive", "v3", credentials=creds, cache_discovery=False)
        self.folder_id = (folder_id or "").strip()


class DriveClientOAuth(_DriveBase):
    """OAuth client — uploads to the signed-in user's own Drive (has quota)."""
    def __init__(self, client_secret_json: str, token_path: str,
                 folder_id: str = ""):
        self.folder_id = (folder_id or "").strip()
        import json as _json
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from google_auth_oauthlib.flow import InstalledAppFlow

        creds = None
        if os.path.exists(token_path):
            # Only reuse the cached token if it was actually GRANTED the scopes we
            # now need (read the stored scopes directly — has_scopes() reflects the
            # requested, not the granted, scopes). A narrower old grant (e.g. the
            # previous drive.file) must be re-consented, never refreshed, or Google
            # returns 'invalid_scope'.
            stored = set()
            try:
                with open(token_path, encoding="utf-8") as f:
                    stored = set(_json.load(f).get("scopes") or [])
            except Exception:
                stored = set()
            if set(SCOPES_OAUTH).issubset(stored):
                try:
                    creds = Credentials.from_authorized_user_file(token_path, SCOPES_OAUTH)
                except Exception:
                    creds = None

        if creds and not creds.valid and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                with open(token_path, "w", encoding="utf-8") as f:
                    f.write(creds.to_json())        # keep the refreshed token
            except Exception:
                creds = None

        if not creds or not creds.valid:
            try:
                if os.path.exists(token_path):
                    os.remove(token_path)      # drop any stale/narrow token
            except Exception:
                pass
            flow = InstalledAppFlow.from_client_secrets_file(
                client_secret_json, SCOPES_OAUTH)
            # access_type=offline -> a refresh token, so the login is remembered
            # and auto-renews for every later operation until the user signs out.
            creds = flow.run_local_server(
                port=0, access_type="offline", prompt="consent")
            with open(token_path, "w", encoding="utf-8") as f:
                f.write(creds.to_json())

        self.service = build("drive", "v3", credentials=creds, cache_discovery=False)
