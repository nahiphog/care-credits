"""Prompt locally for Tavily credentials; never print or commit them."""
import getpass
import os
from pathlib import Path
import re
import secrets


def main():
    root = Path(__file__).resolve().parents[1]
    destination = root / ".env"
    content = (destination if destination.exists() else root / ".env.sample").read_text()
    key = getpass.getpass("Tavily API key (hidden): ").strip()
    if not key or not re.fullmatch(r"[A-Za-z0-9_-]+", key):
        raise SystemExit("Enter a nonempty API key containing letters, digits, underscores or hyphens.")
    values = {"TAVILY_API_KEY": key}
    if not re.search(r"^DISCOVERY_API_TOKEN=\S+", content, flags=re.M):
        values["DISCOVERY_API_TOKEN"] = secrets.token_urlsafe(32)
    for name, value in values.items():
        pattern = r"^" + name + r"=.*$"
        if re.search(pattern, content, flags=re.M):
            content = re.sub(pattern, name + "=" + value, content, flags=re.M)
        else:
            content += "\n" + name + "=" + value + "\n"
    # Restrict permissions before writing, including when updating an existing file.
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as output:
        if hasattr(os, 'fchmod'):
            os.fchmod(output.fileno(), 0o600)
        output.write(content)
    print("Saved credentials in the ignored root .env. Restart the backend to load them.")


if __name__ == "__main__":
    main()
