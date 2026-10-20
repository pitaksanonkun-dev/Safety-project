"""
drive_client.py — minimal Google Drive upload/download via a Service Account.

Online mode uploads the (actual-size) encrypted blob to Google Drive and keeps
only a tiny pointer locally; decrypting the pointer downloads the blob back.

Setup (done once by the user, outside this app):
  1. Create a Google Cloud project, enable the Google Drive API.
  2. Create a Service Account and download its JSON key.
  3. Share a Drive folder (ideally a Shared Drive, which has storage quota) with
     the service account's email, and copy that folder's ID.
  4. In the app: Settings > ตั้งค่า Google Drive — point to the JSON key and
     paste the folder ID.

Dependencies: google-api-python-client, google-auth
"""

from __future__ import annotations

import io

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload, MediaIoBaseDownload

SCOPES = ["https://www.googleapis.com/auth/drive"]


class DriveClient:
    def __init__(self, service_account_json: str, folder_id: str = ""):
        creds = service_account.Credentials.from_service_account_file(
            service_account_json, scopes=SCOPES)
        self.service = build("drive", "v3", credentials=creds,
                             cache_discovery=False)
        self.folder_id = (folder_id or "").strip()

    def upload_bytes(self, data: bytes, name: str,
                     mime: str = "application/octet-stream") -> str:
        """Upload bytes as a new Drive file; return its file id."""
        meta = {"name": name}
        if self.folder_id:
            meta["parents"] = [self.folder_id]
        media = MediaInMemoryUpload(data, mimetype=mime, resumable=False)
        f = self.service.files().create(
            body=meta, media_body=media, fields="id",
            supportsAllDrives=True).execute()
        return f["id"]

    def download_bytes(self, file_id: str) -> bytes:
        """Download a Drive file's content by id."""
        req = self.service.files().get_media(fileId=file_id,
                                             supportsAllDrives=True)
        buf = io.BytesIO()
        downloader = MediaIoBaseDownload(buf, req)
        done = False
        while not done:
            _status, done = downloader.next_chunk()
        return buf.getvalue()

    def check(self) -> str:
        """Quick connectivity/credentials check; returns the account email."""
        about = self.service.about().get(fields="user(emailAddress)").execute()
        return about.get("user", {}).get("emailAddress", "(unknown)")
