"""Store the D2L login in the operating system's credential vault (Windows Credential
Manager / macOS Keychain). Nothing is written to a plain file or to this repository."""
import getpass
import json

SERVICE = "oat-d2l-login"


def _kr():
    import keyring
    return keyring


def load(base):
    try:
        raw = _kr().get_password(SERVICE, base)
    except Exception:
        return None
    return json.loads(raw) if raw else None


def save(base, username, password):
    _kr().set_password(SERVICE, base, json.dumps({"u": username, "p": password}))


def forget(base):
    try:
        _kr().delete_password(SERVICE, base)
    except Exception:
        pass


def prompt(base, current=None):
    """Ask for the login in the terminal (password is not echoed) and save it."""
    default = f" [{current['u']}]" if current else ""
    u = input(f"D2L username{default}: ").strip() or (current or {}).get("u", "")
    p = getpass.getpass("D2L password (hidden, stored only in your OS credential vault): ")
    if not u or not p:
        return None
    try:
        save(base, u, p)
        print("Login saved to the OS credential vault.")
    except Exception as e:
        print("NOT saved (%s). Using it for this run only." % e)
    return {"u": u, "p": p}
