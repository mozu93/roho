import json
import urllib.parse
import urllib.request


_BASE_URL = "https://bank.teraren.com"


class BankMasterService:
    """金融機関コードAPIを使った銀行・支店検索。保存処理とは独立して利用する。"""

    @staticmethod
    def _get(path: str, params: dict) -> list:
        query = urllib.parse.urlencode(params)
        request = urllib.request.Request(
            f"{_BASE_URL}{path}?{query}",
            headers={"User-Agent": "Rouho/1.0"},
        )
        with urllib.request.urlopen(request, timeout=8) as response:
            value = json.loads(response.read().decode("utf-8"))
        if not isinstance(value, list):
            raise ValueError("検索結果の形式が不正です。")
        return value

    def search_banks(self, keyword: str) -> list[dict]:
        keyword = (keyword or "").strip()
        if not keyword:
            raise ValueError("金融機関名を入力してください。")
        param = "code" if keyword.isdigit() else "name"
        return self._get("/banks/search.json", {param: keyword, "per": 50})

    def search_branches(self, bank_code: str, keyword: str) -> list[dict]:
        bank_code = (bank_code or "").strip()
        keyword = (keyword or "").strip()
        if len(bank_code) != 4 or not bank_code.isdigit():
            raise ValueError("先に金融機関を検索して選択してください。")
        if not keyword:
            raise ValueError("支店名を入力してください。")
        param = "code" if keyword.isdigit() else "name"
        return self._get(
            f"/banks/{bank_code}/branches/search.json", {param: keyword, "per": 50}
        )
