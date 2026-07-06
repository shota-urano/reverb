# ERRORS

## 2026-07-05: backend の検証コマンド

- 失敗: 非対話シェルでは `python` が PATH に無く、`python -m pytest` が起動しなかった。
- 成功: `backend/.venv/bin/python -m pytest` を使用する。
- 制約: 管理サンドボックスでは loopback socket の bind が `PermissionError` になるため、
  `test_usl99_delete_e2e.py` の sidecar HTTP テスト2件は実行環境外で確認する。

## 2026-07-06: config の環境変数 helper 追加

- 失敗: `_env_float` の直後へ helper を追加する patch が、既存の `try/except` の途中に入り、
  環境変数指定時だけ `_env_float` が `None` を返した。
- 成功: `_env_float` の `try/except` を元の関数内へ戻し、関数境界の後に
  `_env_optional_float` を追加して設定テストを再実行した。
- 再発防止: 既存関数の近傍へ追加した後は、その関数全体を表示して境界を確認する。
