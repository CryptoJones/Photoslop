#!/usr/bin/env python3
# Revoke the throwaway "Created via API" Apple Development certificates that
# automatic cloud signing mints on CI (#255).
# SPDX-License-Identifier: Apache-2.0
#
# Each tagged release used to leave one behind: the runner's keychain is
# ephemeral, so cloud signing could never reuse the last release's development
# certificate and created another. The account limit is 15, and hitting it
# fails the archive with "choose a certificate to revoke" *after* the tests
# have passed and the app has built. This drains the pile after every upload.
#
# Deliberately narrow: only DEVELOPMENT certificates, and only those whose
# display name is Apple's cloud-signing marker "Created via API". The Apple
# Distribution certificate CI signs releases with is never a candidate.
#
# A permission problem is a warning, not a failure — by the time this runs the
# build is already on TestFlight, and no cleanup problem should turn a shipped
# release red.
#
# Uses only the standard library plus the openssl binary: the App Store
# Connect API wants an ES256 JWT, openssl does the signing, and the DER
# signature it emits is repacked into the raw 64-byte form JWTs carry.

import base64
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

API = "https://api.appstoreconnect.apple.com"
MARKER = "Created via API"


def b64url(data: bytes) -> bytes:
    return base64.urlsafe_b64encode(data).rstrip(b"=")


def der_to_raw(der: bytes) -> bytes:
    """An ECDSA signature from openssl is a DER SEQUENCE of two INTEGERs;
    a JWT wants the two values raw, zero-padded to 32 bytes each."""

    def read_length(buf: bytes, at: int) -> tuple[int, int]:
        first = buf[at]
        if first < 0x80:
            return first, at + 1
        count = first & 0x7F
        return int.from_bytes(buf[at + 1 : at + 1 + count], "big"), at + 1 + count

    if der[0] != 0x30:
        raise ValueError("not a DER sequence")
    _, offset = read_length(der, 1)
    values = []
    for _ in range(2):
        if der[offset] != 0x02:
            raise ValueError("not a DER integer")
        length, start = read_length(der, offset + 1)
        values.append(der[start : start + length].lstrip(b"\x00").rjust(32, b"\x00"))
        offset = start + length
    return b"".join(values)


def token(key_pem_path: str, key_id: str, issuer_id: str) -> str:
    header = b64url(json.dumps({"alg": "ES256", "kid": key_id, "typ": "JWT"}).encode())
    now = int(time.time())
    claims = b64url(
        json.dumps(
            {"iss": issuer_id, "iat": now, "exp": now + 600, "aud": "appstoreconnect-v1"}
        ).encode()
    )
    signing_input = header + b"." + claims
    with tempfile.NamedTemporaryFile(suffix=".txt") as body:
        body.write(signing_input)
        body.flush()
        der = subprocess.run(
            ["openssl", "dgst", "-sha256", "-sign", key_pem_path, body.name],
            check=True,
            capture_output=True,
        ).stdout
    return (signing_input + b"." + b64url(der_to_raw(der))).decode()


def request(method: str, url: str, bearer: str) -> tuple[int, dict]:
    req = urllib.request.Request(url, method=method)
    req.add_header("Authorization", f"Bearer {bearer}")
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            payload = response.read()
            return response.status, json.loads(payload) if payload else {}
    except urllib.error.HTTPError as error:
        payload = error.read()
        try:
            return error.code, json.loads(payload) if payload else {}
        except json.JSONDecodeError:
            return error.code, {}


def main() -> int:
    key_id = os.environ["APP_STORE_CONNECT_KEY_ID"]
    issuer_id = os.environ["APP_STORE_CONNECT_ISSUER_ID"]
    key_b64 = os.environ["APP_STORE_CONNECT_PRIVATE_KEY"]

    with tempfile.NamedTemporaryFile(suffix=".p8") as key_file:
        key_file.write(base64.b64decode(key_b64))
        key_file.flush()
        bearer = token(key_file.name, key_id, issuer_id)

    status, listing = request(
        "GET", f"{API}/v1/certificates?filter[certificateType]=DEVELOPMENT&limit=200", bearer
    )
    if status != 200:
        print(f"::warning::Could not list certificates (HTTP {status}); leaving them be")
        return 0

    doomed = [
        item
        for item in listing.get("data", [])
        if item.get("attributes", {}).get("displayName") == MARKER
    ]
    if not doomed:
        print("No throwaway development certificates to revoke.")
        return 0

    if "--dry-run" in sys.argv:
        for certificate in doomed:
            attributes = certificate.get("attributes", {})
            print(
                f"Would revoke {attributes.get('serialNumber', '?')} "
                f"(expires {attributes.get('expirationDate', '?')})"
            )
        print(f"Dry run: {len(doomed)} throwaway development certificates.")
        return 0

    failures = 0
    for certificate in doomed:
        serial = certificate.get("attributes", {}).get("serialNumber", "?")
        status, _ = request("DELETE", f"{API}/v1/certificates/{certificate['id']}", bearer)
        if status == 204:
            print(f"Revoked throwaway development certificate {serial}.")
        else:
            failures += 1
            print(f"::warning::Could not revoke certificate {serial} (HTTP {status})")

    print(f"Revoked {len(doomed) - failures} of {len(doomed)}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
