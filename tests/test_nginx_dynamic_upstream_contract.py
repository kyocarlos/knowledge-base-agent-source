from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG = (ROOT / "nginx.conf").read_text()


def test_docker_dns_resolver_and_runtime_variable_are_configured():
    assert "resolver 127.0.0.11 valid=5s ipv6=off;" in CONFIG
    assert "set $web_upstream web:8000;" in CONFIG


def test_all_dynamic_proxy_locations_use_runtime_variable():
    assert "proxy_pass http://web:8000;" not in CONFIG
    assert CONFIG.count("proxy_pass http://$web_upstream;") == 10
    assert "proxy_pass http://$web_upstream/ws;" in CONFIG
