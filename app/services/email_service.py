# app/services/email_service.py
import base64
import os
import time
from pathlib import Path
import requests
import msal
from msal_extensions import build_encrypted_persistence, PersistedTokenCache


GRAPH_SEND_URL = "https://graph.microsoft.com/v1.0/me/sendMail"
SCOPES = ["Mail.Send"]
SEND_SHARED_SCOPE = "Mail.Send.Shared"
_CACHE_FILE = Path.home() / ".rouho" / "m365_token_cache_v2.bin"
_LEGACY_CACHE_FILE = Path.home() / ".rouho_token_cache.bin"
MAX_ATTACHMENT_SIZE_BYTES = 3 * 1024 * 1024
MAX_RATE_LIMIT_RETRIES = 3
DEFAULT_RETRY_AFTER_SECONDS = 5


class EmailService:
    def __init__(self, config):
        self._config = config
        _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        # 旧版の平文キャッシュは、Windows の資格情報保護で暗号化する方式へ移行する。
        try:
            _LEGACY_CACHE_FILE.unlink(missing_ok=True)
        except OSError:
            pass
        self._cache = PersistedTokenCache(build_encrypted_persistence(str(_CACHE_FILE)))
        self._app = None

    def _scopes(self) -> list[str]:
        scopes = list(SCOPES)
        if self._config.m365_from_address.strip():
            scopes.append(SEND_SHARED_SCOPE)
        return scopes

    def _get_app(self) -> msal.PublicClientApplication:
        if not self._app:
            self._app = msal.PublicClientApplication(
                self._config.m365_client_id,
                authority=f"https://login.microsoftonline.com/{self._config.m365_tenant_id}",
                token_cache=self._cache,
            )
        return self._app

    def get_token(self) -> str:
        app = self._get_app()
        scopes = self._scopes()
        accounts = app.get_accounts()
        if accounts:
            result = app.acquire_token_silent(scopes, account=accounts[0])
            if result and "access_token" in result:
                return result["access_token"]

        # デバイスコードフロー
        flow = app.initiate_device_flow(scopes=scopes)
        if "user_code" not in flow:
            raise RuntimeError(f"デバイスコードの取得に失敗しました: {flow.get('error_description')}")

        # ユーザーへの案内（呼び出し元がダイアログ表示を担当）
        raise DeviceCodeRequired(flow["message"], flow)

    def acquire_token_with_device_flow(self, flow: dict) -> str:
        app = self._get_app()
        result = app.acquire_token_by_device_flow(flow)
        if "access_token" not in result:
            raise RuntimeError(f"認証エラー: {result.get('error_description', '不明なエラー')}")
        return result["access_token"]

    def get_token_silent(self) -> str:
        """キャッシュ済みトークンを返す。未認証なら RuntimeError を送出する"""
        if not self.is_configured():
            raise RuntimeError("Microsoft 365 の設定（テナントID・クライアントID）が未設定です。設定タブで設定してください。")
        app = self._get_app()
        accounts = app.get_accounts()
        if accounts:
            result = app.acquire_token_silent(self._scopes(), account=accounts[0])
            if result and "access_token" in result:
                return result["access_token"]
        raise RuntimeError(
            "未認証です。「メール送信」タブで Microsoft 365 サインインを行ってください。"
        )

    def is_configured(self) -> bool:
        return bool(self._config.m365_tenant_id and self._config.m365_client_id)

    def is_authenticated(self) -> bool:
        if not self.is_configured():
            return False
        try:
            app = self._get_app()
            return bool(app.get_accounts())
        except Exception:
            return False

    def send(
        self,
        to_address: str,
        subject: str,
        body: str,
        attachments: list[dict] | None = None,
        token: str | None = None,
    ) -> None:
        if token is None:
            app = self._get_app()
            accounts = app.get_accounts()
            if not accounts:
                raise RuntimeError("未認証です。先にサインインしてください。")
            result = app.acquire_token_silent(self._scopes(), account=accounts[0])
            if not result or "access_token" not in result:
                err = (result.get("error_description", "不明") if result else "応答なし")
                raise RuntimeError(f"トークン取得失敗: {err}。再サインインしてください。")
            token = result["access_token"]

        message = {
            "message": {
                "subject": subject,
                "body": {"contentType": "Text", "content": body},
                "toRecipients": [{"emailAddress": {"address": to_address}}],
            },
            "saveToSentItems": "true",
        }

        from_address = self._config.m365_from_address.strip()
        if from_address:
            message["message"]["from"] = {
                "emailAddress": {"address": from_address}
            }

        if attachments:
            total_size = 0
            message["message"]["attachments"] = []
            for att in attachments:
                if not os.path.isfile(att["path"]):
                    raise FileNotFoundError(f"添付ファイルが見つかりません: {att['name']}")
                total_size += os.path.getsize(att["path"])
                if total_size > MAX_ATTACHMENT_SIZE_BYTES:
                    raise ValueError(
                        "添付ファイルの合計サイズが3MBを超えています。"
                        "ファイルを小さくするか、共有リンクをご利用ください。"
                    )
                with open(att["path"], "rb") as f:
                    content = base64.b64encode(f.read()).decode("utf-8")
                message["message"]["attachments"].append({
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "name": att["name"],
                    "contentBytes": content,
                })

        for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
            resp = requests.post(
                GRAPH_SEND_URL,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json=message,
                timeout=30,
            )
            if resp.status_code in (200, 202):
                return
            if resp.status_code == 429 and attempt < MAX_RATE_LIMIT_RETRIES:
                try:
                    wait_seconds = int(resp.headers.get("Retry-After", DEFAULT_RETRY_AFTER_SECONDS))
                except ValueError:
                    wait_seconds = DEFAULT_RETRY_AFTER_SECONDS
                time.sleep(wait_seconds)
                continue
            raise RuntimeError(f"送信エラー ({resp.status_code}): {resp.text[:200]}")


class DeviceCodeRequired(Exception):
    """デバイスコードフロー開始が必要な場合に発生"""
    def __init__(self, message: str, flow: dict):
        super().__init__(message)
        self.flow = flow
