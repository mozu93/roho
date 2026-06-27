# app/services/email_service.py
import base64
import json
import os
import requests
import msal


GRAPH_SEND_URL = "https://graph.microsoft.com/v1.0/me/sendMail"
SCOPES = ["Mail.Send"]
TOKEN_CACHE_FILE = os.path.join(os.path.expanduser("~"), ".rouho_token_cache.bin")


class EmailService:
    def __init__(self, config):
        self._config = config
        self._cache = msal.SerializableTokenCache()
        if os.path.exists(TOKEN_CACHE_FILE):
            with open(TOKEN_CACHE_FILE, "r", encoding="utf-8") as f:
                self._cache.deserialize(f.read())
        self._app = None

    def _get_app(self) -> msal.PublicClientApplication:
        if not self._app:
            self._app = msal.PublicClientApplication(
                self._config.m365_client_id,
                authority=f"https://login.microsoftonline.com/{self._config.m365_tenant_id}",
                token_cache=self._cache,
            )
        return self._app

    def _save_cache(self):
        if self._cache.has_state_changed:
            fd = os.open(TOKEN_CACHE_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(self._cache.serialize())

    def get_token(self) -> str:
        app = self._get_app()
        accounts = app.get_accounts()
        if accounts:
            result = app.acquire_token_silent(SCOPES, account=accounts[0])
            if result and "access_token" in result:
                self._save_cache()
                return result["access_token"]

        # デバイスコードフロー
        flow = app.initiate_device_flow(scopes=SCOPES)
        if "user_code" not in flow:
            raise RuntimeError(f"デバイスコードの取得に失敗しました: {flow.get('error_description')}")

        # ユーザーへの案内（呼び出し元がダイアログ表示を担当）
        raise DeviceCodeRequired(flow["message"], flow)

    def acquire_token_with_device_flow(self, flow: dict) -> str:
        app = self._get_app()
        result = app.acquire_token_by_device_flow(flow)
        if "access_token" not in result:
            raise RuntimeError(f"認証エラー: {result.get('error_description', '不明なエラー')}")
        self._save_cache()
        return result["access_token"]

    def get_token_silent(self) -> str:
        """キャッシュ済みトークンを返す。未認証なら RuntimeError を送出する"""
        app = self._get_app()
        accounts = app.get_accounts()
        if accounts:
            result = app.acquire_token_silent(SCOPES, account=accounts[0])
            if result and "access_token" in result:
                self._save_cache()
                return result["access_token"]
        raise RuntimeError(
            "未認証です。「メール送信」タブで Microsoft 365 サインインを行ってください。"
        )

    def is_authenticated(self) -> bool:
        app = self._get_app()
        return bool(app.get_accounts())

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
            result = app.acquire_token_silent(SCOPES, account=accounts[0])
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

        if attachments:
            message["message"]["attachments"] = []
            for att in attachments:
                with open(att["path"], "rb") as f:
                    content = base64.b64encode(f.read()).decode("utf-8")
                message["message"]["attachments"].append({
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "name": att["name"],
                    "contentBytes": content,
                })

        resp = requests.post(
            GRAPH_SEND_URL,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=message,
            timeout=30,
        )
        if resp.status_code not in (200, 202):
            raise RuntimeError(f"送信エラー ({resp.status_code}): {resp.text[:200]}")


class DeviceCodeRequired(Exception):
    """デバイスコードフロー開始が必要な場合に発生"""
    def __init__(self, message: str, flow: dict):
        super().__init__(message)
        self.flow = flow
