#!/usr/bin/env python3

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"


def ok(msg):
    print(f"{C.GREEN}[OK]{C.RESET}  {msg}")


def err(msg):
    print(f"{C.RED}[ERR]{C.RESET} {msg}", file=sys.stderr)


def warn(msg):
    print(f"{C.YELLOW}[WARN]{C.RESET} {msg}")


def step(msg):
    print(f"{C.BLUE}[....]{C.RESET} {msg}")


def header(title):
    bar = "=" * (len(title) + 4)
    print(f"\n{C.BOLD}{C.WHITE}{bar}{C.RESET}")
    print(f"{C.BOLD}{C.WHITE}  {title}{C.RESET}")
    print(f"{C.BOLD}{C.WHITE}{bar}{C.RESET}\n")


def run(cmd, check=True, capture=False, input_data=None):
    return subprocess.run(
        cmd,
        check=check,
        capture_output=capture,
        text=True,
        input=input_data,
    )


def run_output(cmd, check=False):
    result = subprocess.run(cmd, check=check, capture_output=True, text=True)
    return result.stdout.strip()


def check_gpg():
    if not shutil.which("gpg"):
        err("GPG is not installed. Please install it first.")
        sys.exit(1)


def list_secret_keys():
    output = run_output(
        ["gpg", "--list-secret-keys", "--keyid-format=long", "--with-colons"]
    )

    keys = []
    current = {}

    for line in output.splitlines():
        fields = line.split(":")
        record = fields[0]

        if record == "sec":
            current = {
                "key_id": fields[4] if len(fields) > 4 else "",
                "uids": [],
            }
            keys.append(current)

        elif record == "uid" and current:
            uid = fields[9] if len(fields) > 9 else ""
            if uid:
                current["uids"].append(uid)

    return keys


def pick_key(keys):
    print(f"\n  {C.BOLD}Multiple GPG secret keys found:{C.RESET}\n")

    for i, key in enumerate(keys, start=1):
        uid = key["uids"][0] if key["uids"] else "(no uid)"
        print(
            f"  {C.CYAN}[{i}]{C.RESET} "
            f"{C.BOLD}{key['key_id']}{C.RESET} "
            f"{C.DIM}{uid}{C.RESET}"
        )

    print()

    while True:
        choice = input(
            f"  {C.YELLOW}Select key [1-{len(keys)}]:{C.RESET} "
        ).strip()

        if choice.isdigit() and 1 <= int(choice) <= len(keys):
            return keys[int(choice) - 1]["key_id"]

        warn("Invalid selection.")


def resolve_key_id():
    keys = list_secret_keys()

    if not keys:
        err("No secret GPG keys found.")
        sys.exit(1)

    if len(keys) == 1:
        key_id = keys[0]["key_id"]
        uid = keys[0]["uids"][0] if keys[0]["uids"] else "(no uid)"

        ok(
            f"Using GPG key: "
            f"{C.BOLD}{key_id}{C.RESET} "
            f"{C.DIM}({uid}){C.RESET}"
        )

        return key_id

    return pick_key(keys)


def do_backup():
    header("GPG Key Backup")

    key_id = input(
        f"  {C.CYAN}Enter your GPG Key ID:{C.RESET} "
    ).strip()

    if not key_id:
        err("No key ID provided.")
        sys.exit(1)

    out_dir = Path("gpg-backup")
    out_dir.mkdir(exist_ok=True)

    public_path = out_dir / "public-key.asc"
    private_path = out_dir / "private-key.asc"
    encrypted_path = out_dir / "private-key.asc.gpg"

    #
    # Export public key
    #
    step(f"Exporting public key  -> {public_path}")

    public_result = run(
        ["gpg", "--export", "--armor", key_id],
        check=False,
        capture=True,
    )

    if public_result.returncode != 0 or not public_result.stdout.strip():
        err(f"Failed to export public key for key ID '{key_id}'.")
        sys.exit(1)

    public_path.write_text(public_result.stdout)

    ok("Public key exported.")

    #
    # Export private key
    #
    step(f"Exporting private key -> {private_path}")

    private_result = run(
        ["gpg", "--export-secret-keys", "--armor", key_id],
        check=False,
        capture=True,
    )

    if private_result.returncode != 0 or not private_result.stdout.strip():
        err(f"Failed to export private key for key ID '{key_id}'.")
        sys.exit(1)

    private_path.write_text(private_result.stdout)

    ok("Private key exported.")

    #
    # Encrypt private key
    #
    encrypt = input(
        f"\n{C.YELLOW}Encrypt private key with password? (y/n):{C.RESET} "
    ).strip().lower()

    if encrypt in ("y", "yes"):
        step("Encrypting private key...")

        enc_result = run(
            [
                "gpg",
                "-c",
                "-o",
                str(encrypted_path),
                str(private_path),
            ],
            check=False,
        )

        if enc_result.returncode != 0:
            err("Failed to encrypt private key.")
            sys.exit(1)

        private_path.unlink()

        ok("Private key encrypted successfully.")

    #
    # Summary
    #
    print(f"\n  {C.BOLD}Backup contents:{C.RESET}")

    for file in sorted(out_dir.iterdir()):
        size = file.stat().st_size

        print(
            f"  {C.DIM}{str(file):<40}{C.RESET}"
            f"{C.WHITE}{size:>8} bytes{C.RESET}"
        )

    print()

    ok(
        f"Backup completed successfully.\n"
        f"  {C.DIM}Location:{C.RESET} "
        f"{C.WHITE}{out_dir.resolve()}{C.RESET}"
    )


def import_normal_keys(asc_files):
    imported = 0

    for keyfile in asc_files:
        step(f"Importing: {keyfile.name}")

        result = run(
            ["gpg", "--import", str(keyfile)],
            check=False,
        )

        if result.returncode == 0:
            ok(f"Imported: {keyfile.name}")
            imported += 1
        else:
            warn(f"Failed to import: {keyfile.name}")

    return imported


def import_encrypted_keys(gpg_files):
    imported = 0

    for encfile in gpg_files:
        step(f"Decrypting & importing: {encfile.name}")

        decrypt = subprocess.run(
            ["gpg", "--decrypt", str(encfile)],
            capture_output=True,
            text=True,
        )

        if decrypt.returncode != 0:
            warn(f"Failed to decrypt: {encfile.name}")
            continue

        imported_proc = subprocess.run(
            ["gpg", "--import"],
            input=decrypt.stdout,
            text=True,
        )

        if imported_proc.returncode == 0:
            ok(f"Imported encrypted key: {encfile.name}")
            imported += 1
        else:
            warn(f"Failed to import decrypted key: {encfile.name}")

    return imported


def configure_git_signing():
    key_id = resolve_key_id()

    run(
        ["git", "config", "--global", "user.signingkey", key_id]
    )

    run(
        ["git", "config", "--global", "commit.gpgsign", "true"]
    )

    ok("Git configured for signed commits.")

    print(
        f"\n  {C.DIM}user.signingkey{C.RESET} = "
        f"{C.WHITE}{key_id}{C.RESET}"
    )

    print(
        f"  {C.DIM}commit.gpgsign {C.RESET} = "
        f"{C.WHITE}true{C.RESET}"
    )

    #
    # GPG_TTY
    #
    bashrc = Path.home() / ".bashrc"
    gpg_tty_line = "export GPG_TTY=$(tty)"

    try:
        content = bashrc.read_text() if bashrc.exists() else ""

        if "GPG_TTY" not in content:
            with bashrc.open("a") as file:
                file.write(f"\n{gpg_tty_line}\n")

            ok("Added GPG_TTY to ~/.bashrc")

        else:
            print(
                f"  {C.DIM}GPG_TTY already configured "
                f"in ~/.bashrc{C.RESET}"
            )

    except OSError as e:
        warn(f"Failed to update ~/.bashrc: {e}")


def do_import():
    header("GPG Key Import")

    key_dir_input = input(
        f"  {C.CYAN}Enter directory path containing key files:{C.RESET} "
    ).strip()

    key_dir = Path(key_dir_input)

    if not key_dir.is_dir():
        err(f"Directory '{key_dir}' does not exist.")
        sys.exit(1)

    asc_files = sorted(key_dir.glob("*.asc"))
    gpg_files = sorted(key_dir.glob("*.asc.gpg"))

    if not asc_files and not gpg_files:
        err("No supported key files found.")
        sys.exit(1)

    imported = 0

    imported += import_normal_keys(asc_files)
    imported += import_encrypted_keys(gpg_files)

    if imported == 0:
        err("No keys were successfully imported.")
        sys.exit(1)

    print(
        f"\n  {C.BOLD}Imported "
        f"{imported} key file(s).{C.RESET}"
    )

    print(f"\n  {C.BOLD}Detected secret keys:{C.RESET}")

    run(
        ["gpg", "--list-secret-keys", "--keyid-format=long"],
        check=False,
    )

    configure_git_signing()

    print()

    ok("Import completed successfully.")


def main():
    parser = argparse.ArgumentParser(
        description="GPG key backup/import utility",
        formatter_class=argparse.RawTextHelpFormatter,
    )

    parser.add_argument(
        "-b",
        "--backup",
        action="store_true",
        help="Backup/export GPG keys",
    )

    parser.add_argument(
        "-i",
        "--import",
        dest="import_keys",
        action="store_true",
        help="Import GPG keys",
    )

    args = parser.parse_args()

    if not args.backup and not args.import_keys:
        parser.print_help()
        sys.exit(1)

    check_gpg()

    if args.backup:
        do_backup()

    if args.import_keys:
        do_import()

    print(
        f"\n{C.BOLD}{C.GREEN}"
        f"All requested operations completed."
        f"{C.RESET}\n"
    )


if __name__ == "__main__":
    main()
