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

# Minimal scope: the app only touches files it creates.
SCOPES_SA = ["https://www.googleapis.com/auth/drive"]
SCOPES_OAUTH = ["https://www.googleapis.com/auth/drive.file"]


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

    def make_public(self, file_id: str) -> None:
        """Let anyone with the link read the file (so other accounts can fetch)."""
        self.service.permissions().create(
            fileId=file_id, body={"type": "anyone", "role": "reader"},
            supportsAllDrives=True).execute()

    def delete_file(self, file_id: str) -> None:
        """Delete a file (only the owner can; callers ignore permission errors)."""
        self.service.files().delete(fileId=file_id, supportsAllDrives=True).execute()

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
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from google_auth_oauthlib.flow import InstalledAppFlow

        creds = None
        if os.path.exists(token_path):
            try:
                creds = Credentials.from_authorized_user_file(token_path, SCOPES_OAUTH)
            except Exception:
                creds = None
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    client_secret_json, SCOPES_OAUTH)
                # opens the browser once; Desktop-app clients allow loopback
                creds = flow.run_local_server(port=0, prompt="consent")
            with open(token_path, "w", encoding="utf-8") as f:
                f.write(creds.to_json())
        self.service = build("drive", "v3", credentials=creds, cache_discovery=False)
