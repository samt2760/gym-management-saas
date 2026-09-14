"""Exercise the Mission 13 restricted runtime through a local HTTPS proxy.

The script is deliberately limited to HTTP/TLS validation.  Database, role, and
certificate provisioning remain explicit operator steps so it cannot target a
live database by accident.
"""

from __future__ import annotations

import argparse
import http.client
import re
import ssl
import sys
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import NoReturn, Self

import httpx


class ValidationError(RuntimeError):
    """A request in the security gate did not meet its required result."""


class _ProxyHandler(BaseHTTPRequestHandler):
    upstream_host = "127.0.0.1"
    upstream_port = 8013

    def log_message(self, _format: str, *_args: object) -> None:
        """Keep proxy output free of request paths, cookies, and credentials."""

    def _forward(self) -> None:
        body_length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(body_length) if body_length else None
        headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower() not in {"connection", "host", "content-length"}
        }
        headers["Host"] = self.headers.get("Host", "127.0.0.1")
        if body is not None:
            headers["Content-Length"] = str(len(body))
        connection = http.client.HTTPConnection(self.upstream_host, self.upstream_port)
        try:
            connection.request(self.command, self.path, body=body, headers=headers)
            response = connection.getresponse()
            response_body = response.read()
            self.send_response(response.status, response.reason)
            for key, value in response.getheaders():
                if key.lower() not in {"connection", "transfer-encoding"}:
                    self.send_header(key, value)
            self.end_headers()
            self.wfile.write(response_body)
        finally:
            connection.close()

    do_GET = _forward
    do_POST = _forward


class HttpsProxy:
    def __init__(
        self, certificate: str, private_key: str, listen_port: int, upstream_port: int
    ):
        handler = type(
            "Mission13ProxyHandler", (_ProxyHandler,), {"upstream_port": upstream_port}
        )
        self.server = ThreadingHTTPServer(("127.0.0.1", listen_port), handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certificate, private_key)
        self.server.socket = context.wrap_socket(self.server.socket, server_side=True)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> Self:
        self.thread.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def _csrf_token(response: httpx.Response) -> str:
    match = re.search(
        r'name=["\']csrf_token["\'][^>]*value=["\']([^"\']+)', response.text
    )
    if match is None:
        raise ValidationError("No CSRF form token was rendered.")
    return match.group(1)


def _record(label: str, response: httpx.Response, expected: set[int]) -> None:
    location = response.headers.get("location", "-")
    result = "PASS" if response.status_code in expected else "FAIL"
    print(
        f"REQUEST: {label}\nMETHOD: {response.request.method}\n"
        f"PATH: {response.request.url.path}\nSTATUS: {response.status_code}\n"
        f"LOCATION: {location}\nRESULT: {result}\nDETAIL: expected {sorted(expected)}"
    )
    if result == "FAIL":
        excerpt = re.sub(r"\s+", " ", response.text)[:500]
        raise ValidationError(
            f"FAILED REQUEST: {label}\nEXPECTED: {sorted(expected)}\n"
            f"ACTUAL STATUS: {response.status_code}\nLOCATION: {location}\n"
            f"RESPONSE EXCERPT: {excerpt}"
        )


def _post(
    client: httpx.Client,
    csrf_path: str,
    target_path: str,
    data: dict[str, str],
) -> httpx.Response:
    page = client.get(csrf_path)
    _record(f"csrf for {target_path}", page, {200})
    data["csrf_token"] = _csrf_token(page)
    return client.post(target_path, data=data, follow_redirects=False)


def _login(client: httpx.Client, username: str, password: str) -> None:
    page = client.get("/login")
    _record("login_page", page, {200})
    csrf_cookie = client.cookies.get("csrf_token")
    if not csrf_cookie:
        raise ValidationError("HTTPS login page did not establish a CSRF cookie.")
    response = client.post(
        "/login",
        data={
            "username": username,
            "password": password,
            "csrf_token": _csrf_token(page),
        },
        follow_redirects=False,
    )
    _record("login", response, {303})
    if not client.cookies.get("session"):
        raise ValidationError("HTTPS login did not establish a session cookie.")
    print("COOKIES SENT: session/CSRF presence verified; values redacted")


def _member_id(response: httpx.Response) -> int:
    location = response.headers.get("location", "")
    match = re.fullmatch(r"/members/(\d+)", location)
    if match is None:
        raise ValidationError(
            "Member creation did not redirect to an explicit member URL."
        )
    return int(match.group(1))


def _run_flow(client: httpx.Client, username: str, password: str, suffix: str) -> int:
    _login(client, username, password)
    _record("dashboard", client.get("/dashboard"), {200})
    _record("members", client.get("/members"), {200})
    today = datetime.now(UTC).date().isoformat()
    name = f"Mission 13 {suffix}"
    created = _post(
        client,
        "/register",
        "/members",
        {
            "full_name": name,
            "phone": "5550101",
            "registration_date": today,
            "email": "",
        },
    )
    _record("create member", created, {303})
    member_id = _member_id(created)
    _record("created member after commit", client.get(f"/members/{member_id}"), {200})
    edited = _post(
        client,
        f"/members/{member_id}/edit",
        f"/members/{member_id}/edit",
        {
            "full_name": f"{name} Edited",
            "phone": "5550102",
            "registration_date": today,
            "email": "",
        },
    )
    _record("edit member", edited, {303})
    renewed = _post(
        client,
        f"/members/{member_id}",
        f"/members/{member_id}/renew",
        {"amount": "120", "idempotency_key": f"mission13-{suffix.lower()}"},
    )
    _record("renew membership", renewed, {303})
    _record("payment history", client.get("/payments"), {200})
    deleted = _post(client, f"/members/{member_id}", f"/members/{member_id}/delete", {})
    _record("delete member", deleted, {303})
    _record("deleted state", client.get("/members/deleted"), {200})
    restored = _post(client, "/members/deleted", f"/members/{member_id}/restore", {})
    _record("restore member", restored, {303})
    _record("restored state", client.get(f"/members/{member_id}"), {200})
    return member_id


def run(args: argparse.Namespace) -> None:
    with HttpsProxy(args.certificate, args.private_key, args.port, args.upstream_port):
        base_url = f"https://127.0.0.1:{args.port}"
        with httpx.Client(base_url=base_url, verify=False, timeout=15) as tenant_a:
            tenant_a_member_id = _run_flow(
                tenant_a, args.tenant_a_username, args.password, "A"
            )
            with httpx.Client(base_url=base_url, verify=False, timeout=15) as tenant_b:
                tenant_b_member_id = _run_flow(
                    tenant_b, args.tenant_b_username, args.password, "B"
                )
                _record(
                    "tenant B cannot read A member",
                    tenant_b.get(f"/members/{tenant_a_member_id}"),
                    {403, 404},
                )
                cross_write = _post(
                    tenant_b,
                    "/members",
                    f"/members/{tenant_a_member_id}/edit",
                    {
                        "full_name": "Cross Tenant",
                        "phone": "5559999",
                        "registration_date": datetime.now(UTC).date().isoformat(),
                        "email": "",
                    },
                )
                _record("tenant B cannot modify A member", cross_write, {403, 404})
                _record(
                    "tenant A cannot read B member",
                    tenant_a.get(f"/members/{tenant_b_member_id}"),
                    {403, 404},
                )
                cross_write = _post(
                    tenant_a,
                    "/members",
                    f"/members/{tenant_b_member_id}/edit",
                    {
                        "full_name": "Cross Tenant",
                        "phone": "5559999",
                        "registration_date": datetime.now(UTC).date().isoformat(),
                        "email": "",
                    },
                )
                _record("tenant A cannot modify B member", cross_write, {403, 404})
                logout = _post(tenant_b, "/dashboard", "/logout", {})
                _record("tenant B logout", logout, {303})
            logout = _post(tenant_a, "/dashboard", "/logout", {})
            _record("tenant A logout", logout, {303})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--certificate", required=True)
    parser.add_argument("--private-key", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--tenant-a-username", default="mission13_a")
    parser.add_argument("--tenant-b-username", default="mission13_b")
    parser.add_argument("--port", type=int, default=8443)
    parser.add_argument("--upstream-port", type=int, default=8013)
    return parser.parse_args()


def main() -> NoReturn:
    try:
        run(parse_args())
    except (httpx.HTTPError, OSError, ValidationError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
    raise SystemExit(0)


if __name__ == "__main__":
    main()
