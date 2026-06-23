"""manage_users ルートのテスト（C#5/6/7, V19, V20, V23 連携）。"""

from contextlib import closing


def _read_user(app_module, username):
    with closing(app_module.get_db()) as conn:
        return conn.execute(
            "SELECT username, role, name, is_active, must_change_password "
            "FROM users WHERE username=?",
            (username,),
        ).fetchone()


def test_add_new_user_sets_must_change_password(admin_client, app_module):
    """V23: 管理者が新規追加したユーザーは must_change_password=1。"""
    resp = admin_client.post(
        "/manage_users",
        data={
            "action": "add",
            "mode": "create",
            "username": "taro",
            "password": "Taro-Initial-Passphrase-2026",
            "name": "太郎",
            "role": "worker",
            "color": "#e8f5e9",
        },
    )
    assert resp.status_code == 200
    row = _read_user(app_module, "taro")
    assert row is not None
    assert row[1] == "worker"
    assert row[2] == "太郎"
    assert row[4] == 1  # must_change_password


def test_edit_mode_ignores_form_username(admin_client, app_module):
    """V20: mode=edit のとき、フォームの username は無視され original_username が権威。
    「太郎の修正のつもりが別 ID で新規作成」事故が起きないことを確認。
    """
    # 1) まず taro を作る
    admin_client.post(
        "/manage_users",
        data={
            "action": "add", "mode": "create",
            "username": "taro", "password": "Taro-Initial-Passphrase-2026",
            "name": "太郎", "role": "worker", "color": "#e8f5e9",
        },
    )
    # 2) 編集モードで username 欄を改ざんしても original_username=taro を信用して更新する
    resp = admin_client.post(
        "/manage_users",
        data={
            "action": "add", "mode": "edit",
            "original_username": "taro",
            "username": "hanako",   # ← 改ざん。サーバは無視するはず
            "name": "太郎２", "role": "worker", "color": "#fff8e1",
            # パスワード空欄 → 据え置き
        },
    )
    assert resp.status_code == 200
    # taro は表示名と色が更新されている
    taro = _read_user(app_module, "taro")
    assert taro is not None
    assert taro[2] == "太郎２"
    # hanako は作られていない
    assert _read_user(app_module, "hanako") is None


def test_edit_mode_with_missing_original_username_is_rejected(admin_client, app_module):
    """V20: mode=edit で original_username が存在しないと flash で拒否され、新規作成も発生しない。"""
    resp = admin_client.post(
        "/manage_users",
        data={
            "action": "add", "mode": "edit",
            "original_username": "ghost",
            "username": "ghost",
            "name": "幽霊", "role": "worker", "color": "#e8f5e9",
            "password": "ghostpass1",
        },
    )
    assert resp.status_code == 200
    assert _read_user(app_module, "ghost") is None


def test_create_mode_duplicate_rejected(admin_client, app_module):
    """V20: mode=create で既存 ID は重複として弾く。"""
    admin_client.post(
        "/manage_users",
        data={
            "action": "add", "mode": "create",
            "username": "taro", "password": "Taro-Initial-Passphrase-2026",
            "name": "太郎", "role": "worker", "color": "#e8f5e9",
        },
    )
    # 同じ ID で別人を作ろうとする
    admin_client.post(
        "/manage_users",
        data={
            "action": "add", "mode": "create",
            "username": "taro", "password": "x9999999",
            "name": "別の太郎", "role": "admin", "color": "#000000",
        },
    )
    taro = _read_user(app_module, "taro")
    # 元の "太郎" のままで上書きされない
    assert taro[2] == "太郎"
    assert taro[1] == "worker"


def test_delete_action_is_rejected(admin_client, app_module):
    """V19: action=delete は flash で拒否されるだけで、ユーザーは消えない。"""
    admin_client.post(
        "/manage_users",
        data={
            "action": "add", "mode": "create",
            "username": "taro", "password": "Taro-Initial-Passphrase-2026",
            "name": "太郎", "role": "worker", "color": "#e8f5e9",
        },
    )
    assert _read_user(app_module, "taro") is not None
    resp = admin_client.post(
        "/manage_users",
        data={"action": "delete", "username": "taro"},
    )
    assert resp.status_code == 200
    # 削除されていないこと
    assert _read_user(app_module, "taro") is not None


def test_delete_button_not_in_html(admin_client):
    """V19: UI からも削除ボタンが撤去されている。停止ボタンは残っている。"""
    # 停止ボタンは admin 以外の行にしか出ないので、職員を 1 名作ってから確認
    admin_client.post(
        "/manage_users",
        data={
            "action": "add", "mode": "create",
            "username": "taro", "password": "Taro-Initial-Passphrase-2026",
            "name": "太郎", "role": "worker", "color": "#e8f5e9",
        },
    )
    resp = admin_client.get("/manage_users")
    body = resp.get_data(as_text=True)
    assert 'name="action" value="delete"' not in body
    assert 'name="action" value="toggle"' in body


def test_self_demotion_blocked(admin_client, app_module):
    """C#5: 自分自身の権限変更は拒否される（自己降格による締め出し防止）。"""
    resp = admin_client.post(
        "/manage_users",
        data={
            "action": "add", "mode": "edit",
            "original_username": "admin", "username": "admin",
            "name": "管理者", "role": "worker", "color": "#2196F3",
        },
    )
    assert resp.status_code == 200
    admin_row = _read_user(app_module, "admin")
    assert admin_row[1] == "admin"  # 降格されていない


def test_duplicate_display_name_rejected(admin_client, app_module):
    """C#6: 表示名重複は拒否される。"""
    admin_client.post(
        "/manage_users",
        data={
            "action": "add", "mode": "create",
            "username": "taro", "password": "Taro-Initial-Passphrase-2026",
            "name": "山田", "role": "worker", "color": "#e8f5e9",
        },
    )
    admin_client.post(
        "/manage_users",
        data={
            "action": "add", "mode": "create",
            "username": "hanako", "password": "hanapass1",
            "name": "山田", "role": "worker", "color": "#fff8e1",
        },
    )
    assert _read_user(app_module, "hanako") is None


def test_forbidden_chars_in_name_rejected(admin_client, app_module):
    """C#7: URL 危険文字 / 改行は表示名に使えない。"""
    admin_client.post(
        "/manage_users",
        data={
            "action": "add", "mode": "create",
            "username": "taro", "password": "Taro-Initial-Passphrase-2026",
            "name": "../etc/passwd", "role": "worker", "color": "#e8f5e9",
        },
    )
    assert _read_user(app_module, "taro") is None


def test_toggle_user_active_state(admin_client, app_module):
    """C#5: 通常の停止/復活フローは成功する。"""
    admin_client.post(
        "/manage_users",
        data={
            "action": "add", "mode": "create",
            "username": "taro", "password": "Taro-Initial-Passphrase-2026",
            "name": "太郎", "role": "worker", "color": "#e8f5e9",
        },
    )
    # 停止
    admin_client.post(
        "/manage_users",
        data={"action": "toggle", "username": "taro", "current_status": "1"},
    )
    assert _read_user(app_module, "taro")[3] == 0
    # 復活
    admin_client.post(
        "/manage_users",
        data={"action": "toggle", "username": "taro", "current_status": "0"},
    )
    assert _read_user(app_module, "taro")[3] == 1


def test_toggle_uses_database_state_not_stale_hidden_value(
    admin_client, app_module
):
    admin_client.post(
        "/manage_users",
        data={
            "action": "add", "mode": "create",
            "username": "taro",
            "password": "Taro-Initial-Passphrase-2026",
            "name": "太郎", "role": "worker", "color": "#e8f5e9",
        },
    )
    admin_client.post(
        "/manage_users",
        data={
            "action": "toggle",
            "username": "taro",
            "current_status": "0",
        },
    )
    assert _read_user(app_module, "taro")[3] == 0
