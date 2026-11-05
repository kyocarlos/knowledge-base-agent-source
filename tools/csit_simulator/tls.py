"""A throw-away certificate authority and server certificate, so a real KM (which insists on HTTPS) can reach the simulator.

KM trusts the CA by setting SSL_CERT_FILE to ca.pem; the server certificate names the simulator's DNS name(s) and 127.0.0.1. DEV only.
"""
from __future__ import annotations

import datetime as dt
import ipaddress
from pathlib import Path


def ensure(directory: str | Path, names: list[str]) -> dict[str, Path]:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    out = {k: d / k for k in ("ca.pem", "server.pem", "server.key")}
    if all(p.is_file() for p in out.values()):
        cert = x509.load_pem_x509_certificate(out["server.pem"].read_bytes())
        have = set(cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.DNSName))
        if set(names) <= have and cert.not_valid_after_utc > dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=7):
            return out
    now = dt.datetime.now(dt.timezone.utc)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "CSIT simulator DEV CA")])
    ca = (x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name).public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
          .not_valid_before(now - dt.timedelta(minutes=5)).not_valid_after(now + dt.timedelta(days=3650))
          .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True).sign(ca_key, hashes.SHA256()))
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    sans = [x509.DNSName(n) for n in names] + [x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
    cert = (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, names[0])])).issuer_name(ca_name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(minutes=5))
            .not_valid_after(now + dt.timedelta(days=365)).add_extension(x509.SubjectAlternativeName(sans), critical=False)
            .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False).sign(ca_key, hashes.SHA256()))
    out["ca.pem"].write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    out["server.pem"].write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    out["server.key"].write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    try:
        out["server.key"].chmod(0o600)
    except OSError:
        pass
    return out
