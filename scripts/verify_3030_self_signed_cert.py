#!/usr/bin/env python3
"""Read-only verification that 3030 serves the configured self-signed cert."""
from __future__ import annotations

import argparse
import hashlib
import socket
import ssl
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import serialization


def fingerprint(cert_der: bytes) -> str:
    return hashlib.sha256(cert_der).hexdigest().upper()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cert", type=Path, default=Path("/home/da40_ai_gb10/nginx_certs/cert.pem"))
    parser.add_argument("--host", default="61.216.9.52")
    parser.add_argument("--port", type=int, default=3030)
    args = parser.parse_args()

    pem = args.cert.read_bytes()
    local = x509.load_pem_x509_certificate(pem)
    context = ssl.create_default_context(cafile=str(args.cert))
    with socket.create_connection((args.host, args.port), timeout=10) as raw:
        with context.wrap_socket(raw, server_hostname=args.host) as tls:
            remote_der = tls.getpeercert(binary_form=True)
            if not remote_der:
                raise SystemExit("FAIL: 3030 returned no peer certificate")
    remote = x509.load_der_x509_certificate(remote_der)
    local_fp = fingerprint(local.public_bytes(serialization.Encoding.DER))
    remote_fp = fingerprint(remote_der)
    if local_fp != remote_fp:
        raise SystemExit(f"FAIL: fingerprint mismatch local={local_fp} remote={remote_fp}")
    san = local.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    names = {str(value) for value in san.get_values_for_type(x509.IPAddress)}
    names.update(san.get_values_for_type(x509.DNSName))
    if args.host not in names:
        raise SystemExit(f"FAIL: SAN does not contain {args.host}")
    print(f"PASS fingerprint={remote_fp} san_contains={args.host} tls_verify=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
