"""Create (or reset) the admin account of the test stack. The password is typed here, by you, and is only ever stored as a hash in the test stack's own SQLite store.
    docker exec -it km-acl-test-web python -m tools.zone_acl_testbed.make_admin
"""
import getpass
import sys

from src.km_control import ControlRegistry

name = (input("管理者帳號名稱 [admin]: ").strip() or "admin").lower()
pw = getpass.getpass("設定密碼(至少 12 個字元): ")
if len(pw) < 12 or pw != getpass.getpass("再輸入一次: "):
    sys.exit("密碼太短或兩次不一致,沒有建立。")
reg = ControlRegistry.from_environment()
user = next((u for u in reg.list_users() if u.username == name), None) or reg.register(name, pw)
from src.km_accounts import hash_password  # noqa: E402

with reg._connection() as c:
    c.execute(reg._sql("UPDATE km_users SET password_hash = ?, status = 'active', is_admin = ?, session_epoch = session_epoch + 1 WHERE user_id = ?"), (hash_password(pw), 1, user.user_id))
print(f"已建立/更新管理者 {name}。請到 http://127.0.0.1:8800/login.html 登入,再開 /control-admin.html。")
