import secrets
import unicodedata


PASSWORD_MIN_LEN = 8
PASSWORD_MAX_LEN = 128

# オフラインで判定し、入力されたパスワードを外部サービスへ送信しない。
# 8文字運用に合わせ、頻出の弱いパスワードだけを最小限ブロックする。
COMMON_PASSWORDS = {
    "password",
    "password1",
    "passw0rd",
    "12345678",
    "123456789",
    "1234567890",
    "qwertyui",
    "qwerty123",
    "00000000",
    "11111111",
    "iloveyou",
    "welcome1",
    "letmein1",
    "shiftflow",
    "adminadmin",
    "administrator",
    # 実運用で選ばれやすい弱い候補を最小限追加（年号付き・サービス名由来）。
    "shiftflow2026",
    "shiftflow2025",
    "password2026",
    "password2025",
    "admin1234",
    "shift1234",
}


def normalize_password(password):
    if password is None:
        return None
    return unicodedata.normalize("NFC", password)


def password_error(password, username=""):
    normalized = normalize_password(password)
    if normalized is None or len(normalized) < PASSWORD_MIN_LEN:
        return f"パスワードは{PASSWORD_MIN_LEN}文字以上で入力してください"
    if len(normalized) > PASSWORD_MAX_LEN:
        return f"パスワードは{PASSWORD_MAX_LEN}文字以内で入力してください"
    folded = normalized.casefold()
    if folded in COMMON_PASSWORDS:
        return "推測されやすいパスワードは使用できません"
    if username and folded == username.casefold():
        return "ユーザーIDと同じパスワードは使用できません"
    if len(set(folded)) == 1:
        return "同じ文字だけのパスワードは使用できません"
    for unit_length in range(1, min(8, len(folded) // 2) + 1):
        if len(folded) % unit_length == 0:
            unit = folded[:unit_length]
            if unit * (len(folded) // unit_length) == folded:
                return "同じ並びを繰り返すパスワードは使用できません"
    return None


def is_valid_password(password, username=""):
    return password_error(password, username) is None


def generate_temporary_password():
    # token_urlsafe(18) は通常24文字。文字種ルールに依存せず十分な長さを確保する。
    return secrets.token_urlsafe(18)
