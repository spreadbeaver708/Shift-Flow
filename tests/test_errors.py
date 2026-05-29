"""カスタムエラーページのテスト（V14）。

403 と 404 は通常の test_client 経由でトリガできる。
500 は Flask の test_client が既定で例外を伝播する（TESTING=True）ため、
このテスト内で一時的に PROPAGATE_EXCEPTIONS=False に切り替え、
test 用の例外送出ルートを追加してハンドラの描画を検証する。
"""


def test_403_returns_custom_template(client):
    """N: 職員ログインで /admin → 403。V14: カスタム HTML が返る。"""
    # 職員を作成 → 強制パスワード変更 → 再ログイン
    client.post("/login", data={"username": "admin", "password": "adminpass1"})
    client.post(
        "/change_password",
        data={"password_current": "adminpass1", "password_new": "adminpass2"},
    )
    client.post("/login", data={"username": "admin", "password": "adminpass2"})
    client.post(
        "/manage_users",
        data={
            "action": "add", "mode": "create",
            "username": "taro", "password": "taropass1",
            "name": "太郎", "role": "worker", "color": "#e8f5e9",
        },
    )
    client.get("/logout")
    client.post("/login", data={"username": "taro", "password": "taropass1"})
    client.post(
        "/change_password",
        data={"password_current": "taropass1", "password_new": "taropass2"},
    )
    client.post("/login", data={"username": "taro", "password": "taropass2"})

    resp = client.get("/admin")
    assert resp.status_code == 403
    body = resp.get_data(as_text=True)
    assert "403" in body
    assert "この画面にはアクセスできません" in body
    # 認証済みなのでメニューへの導線
    assert "メニューに戻る" in body


def test_404_returns_custom_template_anonymous(client):
    """V14: 未ログインで存在しない URL → 404 カスタム HTML（ログインへの導線）。"""
    resp = client.get("/this-path-does-not-exist")
    assert resp.status_code == 404
    body = resp.get_data(as_text=True)
    assert "404" in body
    assert "ページが見つかりません" in body
    # 未ログインなのでログインへの導線
    assert "ログイン画面へ" in body


def test_404_returns_custom_template_logged_in(client):
    """V14: ログイン済みで 404 → メニューへの導線が出る。"""
    client.post("/login", data={"username": "admin", "password": "adminpass1"})
    client.post(
        "/change_password",
        data={"password_current": "adminpass1", "password_new": "adminpass2"},
    )
    client.post("/login", data={"username": "admin", "password": "adminpass2"})

    resp = client.get("/this-path-does-not-exist")
    assert resp.status_code == 404
    body = resp.get_data(as_text=True)
    assert "メニューに戻る" in body


def test_500_returns_custom_template(client, app_module):
    """V14: 500 エラーでスタックトレースを返さず、カスタム HTML を返す。"""
    # 一時的に例外伝播を止め、強制 500 ルートを登録
    app_module.app.config["TESTING"] = False
    app_module.app.config["PROPAGATE_EXCEPTIONS"] = False

    @app_module.app.route("/__force_500__")
    def _boom():
        raise RuntimeError("synthetic failure for V14 test")

    try:
        resp = client.get("/__force_500__")
        assert resp.status_code == 500
        body = resp.get_data(as_text=True)
        assert "500" in body
        assert "サーバー側でエラーが発生しました" in body
        # スタックトレースが漏れていないこと
        assert "synthetic failure" not in body
        assert "Traceback" not in body
    finally:
        app_module.app.config["TESTING"] = True
        app_module.app.config["PROPAGATE_EXCEPTIONS"] = None


def test_error_pages_have_security_headers(client):
    """V9 と V14 の併用: エラーレスポンスにもセキュリティヘッダが付く。"""
    resp = client.get("/this-path-does-not-exist")
    assert resp.status_code == 404
    assert resp.headers.get("X-Frame-Options") == "DENY"
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
