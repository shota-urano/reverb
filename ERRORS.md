# ERRORS

## 2026-07-05: backend の検証コマンド

- 失敗: 非対話シェルでは `python` が PATH に無く、`python -m pytest` が起動しなかった。
- 成功: `backend/.venv/bin/python -m pytest` を使用する。
- 制約: 管理サンドボックスでは loopback socket の bind が `PermissionError` になるため、
  `test_usl99_delete_e2e.py` の sidecar HTTP テスト2件は実行環境外で確認する。
