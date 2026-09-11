import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from py_vapid import Vapid, b64urlencode


def main() -> None:
    vapid = Vapid()
    vapid.generate_keys()
    private_key = vapid.private_pem().decode("utf-8").strip().replace("\n", "\\n")
    public_numbers = vapid.public_key.public_numbers()
    public_raw = (
        b"\x04"
        + public_numbers.x.to_bytes(32, "big")
        + public_numbers.y.to_bytes(32, "big")
    )
    public_key = b64urlencode(public_raw)

    print("Cole estas variaveis no Coolify:")
    print(f"VAPID_PRIVATE_KEY={private_key}")
    print(f"VAPID_PUBLIC_KEY={public_key}")
    print("VAPID_SUBJECT=mailto:contato@centralaguas.com.br")


if __name__ == "__main__":
    main()
