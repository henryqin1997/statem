from __future__ import annotations

import atexit
import argparse
import hashlib
import json
import os
import pwd
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


FAMILY = "git_webserver_deploy"
VERSION = 1
GATE_TIMEOUT_SECONDS = float(os.environ.get("STATEM_GIT_WEBSERVER_CHECK_TIMEOUT", "90"))
DEFAULT_TASK = Path("/tmp/statem-verification-checks/task.txt")
DEFAULT_SELECTION = Path("/tmp/statem-verification-checks/git-webserver-selection.json")
DEFAULT_CONTRACT = Path("/tmp/statem-verification-checks/task-contract-receipt.json")
DEFAULT_REVIEW = Path("/tmp/statem-verification-checks/self-review.json")
DEFAULT_RECEIPT = Path("/tmp/statem-verification-checks/git-webserver-receipt.json")
DEFAULT_DEADLINE = Path("/tmp/statem-verification-checks/deadline.json")
REQUIRED_HINTS = (
    "ssh_user",
    "repo_path",
    "branch",
    "web_file",
    "expected_content",
    "web_url",
)
PRACTICE = {
    "id": FAMILY,
    "role": "reviewer",
    "instruction": (
        "Review the exact consumer path, not just the local implementation: a fresh client must "
        "clone the configured bare repository over SSH as the named user, commit and push the "
        "requested branch, and then fetch the exact expected body from the public HTTP URL. "
        "Treat repository existence, an executable hook, an open port, a direct write into the web "
        "root, and a curl against pre-existing content as separate partial observations, not proof "
        "of the end-to-end deployment contract. Preserve a working candidate and repair a concrete "
        "broken link before considering rollback."
    ),
    "review_questions": [
        "Does the configured SSH user reach the exact bare repository path from the prompt?",
        "Does a new push to the requested branch trigger deployment without an agent-side copy?",
        "Does a fresh HTTP request observe the pushed file with byte-exact body content?",
        "Could the current evidence be stale, circular, or produced through a privileged shortcut?",
    ],
    "required_evidence": [
        "fresh SSH clone",
        "fresh commit and push to the requested branch",
        "post-push HTTP body equality",
        "post-check repository ref and HTTP freshness",
    ],
    "anti_patterns": [
        "writing directly to the web root",
        "testing only localhost content created before the push",
        "checking only that sshd, Git, a hook, or an HTTP port exists",
        "replacing a failed end-to-end check with a proxy assertion",
    ],
}


def extract_hints(task_text: str) -> dict[str, str]:
    import re

    hints: dict[str, str] = {}
    remote = re.search(r"\b([A-Za-z0-9._-]+)@([A-Za-z0-9._-]+):(/[^\s'\"`]+)", task_text)
    if remote:
        hints["ssh_user"] = remote.group(1)
        hints["prompt_host"] = remote.group(2)
        hints["repo_path"] = remote.group(3).rstrip(".,)")

    url = re.search(r"https?://[^\s'\"`]+", task_text)
    if url:
        hints["web_url"] = url.group(0).rstrip(".,)")

    echo = re.search(r"\becho\s+([\"'])(.*?)\1\s*>\s*([A-Za-z0-9_./-]+)", task_text)
    if echo:
        hints["expected_content"] = echo.group(2)
        hints["web_file"] = echo.group(3).rstrip(".,)")

    push = re.search(r"\bgit\s+push\s+origin\s+([A-Za-z0-9_./-]+)", task_text)
    if push:
        hints["branch"] = push.group(1).rstrip(".,)")
    return hints


def select_family(task_text: str) -> dict[str, Any]:
    lower = task_text.lower()
    hints = extract_hints(task_text)
    selected = bool(
        all(str(hints.get(key) or "").strip() for key in REQUIRED_HINTS)
        and "git clone" in lower
        and "git push" in lower
        and ("curl " in lower or "http request" in lower or "webserver" in lower)
    )
    basis = (
        "task_visible_git_ssh_push_http_contract"
        if selected
        else "no_high_confidence_git_ssh_push_http_contract"
    )
    payload: dict[str, Any] = {
        "version": VERSION,
        "selected": selected,
        "family": FAMILY,
        "selection_basis": basis,
        "applies_in_state": "self_review",
        "practice": PRACTICE if selected else None,
        "gate": {
            "name": FAMILY,
            "effect_scope": "stateful",
            "git_webserver_hints": hints if selected else {},
        },
        "limits": [
            "solve the visible task normally before loading family review practice",
            "execute at most one stateful family gate per evidence-state entry",
            "repair concrete failures non-destructively before considering rollback",
            "under handoff deadline pressure preserve the best runnable candidate",
        ],
    }
    payload["selection_fingerprint"] = _selection_fingerprint(payload)
    return payload


def validate_selection(selection: Any, task_text: str) -> list[str]:
    expected = select_family(task_text)
    if not isinstance(selection, dict):
        return ["family selection must be a JSON object"]
    if selection != expected:
        return [
            "family selection does not exactly match the task-visible contract; "
            "regenerate it instead of editing routes, hints, practice, or limits"
        ]
    return []


def render_practice(selection: dict[str, Any], task_text: str) -> str:
    _raise_errors(validate_selection(selection, task_text))
    if not selection["selected"]:
        return ""
    practice = selection["practice"]
    lines = [
        "Selected reviewer practice: git_webserver_deploy",
        str(practice["instruction"]),
        "Review questions:",
    ]
    lines.extend(f"- {item}" for item in practice["review_questions"])
    lines.append("Required evidence:")
    lines.extend(f"- {item}" for item in practice["required_evidence"])
    lines.append("Reject these proxy checks:")
    lines.extend(f"- {item}" for item in practice["anti_patterns"])
    return "\n".join(lines)


def initial_contract() -> dict[str, Any]:
    return {
        "version": 1,
        "source": "agent",
        "status": "pending",
        "artifact_or_service_identity": "",
        "checks": [],
        "remaining_risk": "",
        "next_action": "",
    }


def validate_contract(receipt: Any) -> list[str]:
    if not isinstance(receipt, dict):
        return ["task contract receipt must be a JSON object"]
    problems: list[str] = []
    if not str(receipt.get("source") or "").startswith("agent"):
        problems.append("task contract receipt source must start with 'agent'")
    status = str(receipt.get("status") or "").strip().lower()
    if status not in {"passed", "failed"}:
        problems.append("task contract receipt status must be passed or failed")
    checks = receipt.get("checks")
    if not isinstance(checks, list) or not any(_meaningful(item) for item in checks):
        problems.append("task contract receipt needs at least one concrete current check")
    if status == "passed":
        if not _meaningful(receipt.get("artifact_or_service_identity")):
            problems.append("passed task contract receipt needs artifact_or_service_identity")
        if receipt.get("next_action") != "self_review":
            problems.append("passed task contract receipt next_action must be self_review")
    if status == "failed" and receipt.get("next_action") != "repair":
        problems.append("failed task contract receipt next_action must be repair")
    return problems


def initial_review(selection: dict[str, Any]) -> dict[str, Any]:
    lenses = {
        "task_contract": {"evidence": ""},
        "evidence_freshness": {"evidence": ""},
        "edge_risk": {"evidence": ""},
    }
    if selection.get("selected"):
        lenses["consumer_path"] = {"evidence": ""}
    return {
        "version": 1,
        "source": "agent",
        "mode": "bounded",
        "status": "pending",
        "family": FAMILY if selection.get("selected") else None,
        "lenses": lenses,
        "findings": [],
        "evidence_gaps": [],
        "next_fix": "",
        "residual_risk": "",
    }


def validate_review(review: Any, selection: Any, task_text: str) -> list[str]:
    problems = validate_selection(selection, task_text)
    safe_selection = selection if isinstance(selection, dict) else {}
    if not isinstance(review, dict):
        return problems + ["self-review must be a JSON object"]
    if not str(review.get("source") or "").startswith("agent"):
        problems.append("self-review source must start with 'agent'")
    if review.get("mode") not in {"bounded", "deadline_bounded"}:
        problems.append("self-review mode must be bounded or deadline_bounded")
    expected_family = FAMILY if safe_selection.get("selected") else None
    if review.get("family") != expected_family:
        problems.append("self-review family must match the immutable selection")

    status = str(review.get("status") or "").strip().lower()
    if status not in {"clean", "issues_found", "needs_evidence", "deadline_handoff"}:
        problems.append(
            "self-review status must be clean, issues_found, needs_evidence, or deadline_handoff"
        )
        return problems

    lenses = review.get("lenses") if isinstance(review.get("lenses"), dict) else {}
    required_lenses = ["task_contract", "evidence_freshness", "edge_risk"]
    if safe_selection.get("selected"):
        required_lenses.append("consumer_path")
    for name in required_lenses:
        lens = lenses.get(name) if isinstance(lenses, dict) else None
        evidence = lens.get("evidence") if isinstance(lens, dict) else ""
        if not _meaningful(evidence, minimum=12):
            problems.append(f"self-review lens {name} needs concrete evidence")

    findings = review.get("findings")
    gaps = review.get("evidence_gaps")
    if status == "clean":
        if _has_open_items(findings) or _has_open_items(gaps):
            problems.append("clean self-review cannot retain open findings or evidence gaps")
    elif status == "issues_found":
        if not _has_open_items(findings):
            problems.append("issues_found self-review needs at least one concrete finding")
        if not _meaningful(review.get("next_fix"), minimum=8):
            problems.append("issues_found self-review needs a concrete next_fix")
    elif status == "needs_evidence":
        if not safe_selection.get("selected"):
            problems.append("needs_evidence requires a selected fixed family gate")
        if not _has_open_items(gaps):
            problems.append("needs_evidence self-review needs at least one concrete evidence gap")
    else:
        if review.get("mode") != "deadline_bounded":
            problems.append("deadline_handoff self-review mode must be deadline_bounded")
        if not _meaningful(review.get("residual_risk"), minimum=12):
            problems.append("deadline_handoff self-review needs specific residual_risk")
    return problems


def run_gate(
    selection: Any,
    task_text: str,
    receipt_path: Path,
) -> tuple[bool, dict[str, Any]]:
    selection_errors = validate_selection(selection, task_text)
    safe_selection = selection if isinstance(selection, dict) else {}
    messages: list[str] = []
    passed = False
    if selection_errors:
        messages.extend(selection_errors)
    elif not safe_selection.get("selected"):
        messages.append("git_webserver_deploy is not selected for this task")
    else:
        try:
            passed, raw_messages = run_git_webserver_check(
                {"git_webserver_hints": safe_selection["gate"]["git_webserver_hints"]}
            )
            messages.extend(str(item)[:500] for item in raw_messages[:30])
        except Exception as exc:  # The failed receipt must survive an unexpected checker error.
            messages.append(f"git_webserver_deploy checker raised {type(exc).__name__}: {exc}")
            passed = False

    hints = safe_selection.get("gate", {}).get("git_webserver_hints", {})
    branch_head = _branch_head(hints) if passed else ""
    observed_url, observed_body, observation_error = _observe_http(hints) if passed else ("", "", "")
    expected = str(hints.get("expected_content") or "") if isinstance(hints, dict) else ""
    if passed and (not branch_head or observation_error or observed_body != expected):
        passed = False
        if not branch_head:
            messages.append("post-gate freshness check could not resolve the deployed branch head")
        if observation_error:
            messages.append(observation_error)
        elif observed_body != expected:
            messages.append(
                f"post-gate HTTP body was {observed_body!r}, expected {expected!r}"
            )

    receipt = {
        "version": 1,
        "source": "statem_fixed_family_gate",
        "family": FAMILY,
        "gate": FAMILY,
        "effect_scope": "stateful",
        "status": "passed" if passed else "failed",
        "selection_fingerprint": safe_selection.get("selection_fingerprint"),
        "gate_implementation_sha256": _implementation_sha256(),
        "recorded_at_epoch": time.time(),
        "branch_head": branch_head,
        "observed_url": observed_url,
        "observed_body": observed_body,
        "messages": messages,
    }
    _write_json(receipt_path, receipt)
    return passed, receipt


def validate_receipt(
    receipt: Any,
    selection: Any,
    task_text: str,
    *,
    max_age_seconds: int = 900,
    now: float | None = None,
) -> list[str]:
    problems = validate_selection(selection, task_text)
    safe_selection = selection if isinstance(selection, dict) else {}
    if not safe_selection.get("selected"):
        problems.append("a family gate receipt is invalid when the family route is not selected")
    if not isinstance(receipt, dict):
        return problems + ["family gate receipt must be a JSON object"]
    expected_fields = {
        "source": "statem_fixed_family_gate",
        "family": FAMILY,
        "gate": FAMILY,
        "effect_scope": "stateful",
        "status": "passed",
        "selection_fingerprint": safe_selection.get("selection_fingerprint"),
    }
    for key, expected in expected_fields.items():
        if receipt.get(key) != expected:
            problems.append(f"family gate receipt {key} must equal {expected!r}")

    current_gate_hash = _implementation_sha256()
    if not current_gate_hash or receipt.get("gate_implementation_sha256") != current_gate_hash:
        problems.append("family gate receipt does not match the current fixed gate implementation")

    recorded = _as_float(receipt.get("recorded_at_epoch"))
    current_time = time.time() if now is None else now
    if recorded is None:
        problems.append("family gate receipt needs recorded_at_epoch")
    elif recorded > current_time + 5:
        problems.append("family gate receipt timestamp is in the future")
    elif current_time - recorded > max_age_seconds:
        problems.append("family gate receipt is older than the allowed freshness window")

    hints = safe_selection.get("gate", {}).get("git_webserver_hints", {})
    current_head = _branch_head(hints)
    if not current_head:
        problems.append("current deployed branch head is unavailable")
    elif receipt.get("branch_head") != current_head:
        problems.append("deployed branch changed after the family gate receipt")

    observed_url, observed_body, observation_error = _observe_http(hints)
    expected_body = str(hints.get("expected_content") or "") if isinstance(hints, dict) else ""
    if observation_error:
        problems.append(observation_error)
    elif observed_body != expected_body:
        problems.append(
            f"current HTTP body was {observed_body!r}, expected {expected_body!r}"
        )
    if receipt.get("observed_url") != observed_url:
        problems.append("family gate receipt URL does not match the current consumer URL")
    if receipt.get("observed_body") != expected_body:
        problems.append("family gate receipt does not record the expected HTTP body")
    return problems


def _selection_fingerprint(payload: dict[str, Any]) -> str:
    canonical = {key: value for key, value in payload.items() if key != "selection_fingerprint"}
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _implementation_sha256() -> str:
    path = Path(__file__)
    if not path.is_file():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_git_webserver_check(selection: dict[str, Any]) -> tuple[bool, list[str]]:
    hints = selection.get("git_webserver_hints") if isinstance(selection, dict) else {}
    hints = hints if isinstance(hints, dict) else {}
    ssh_user = str(hints.get("ssh_user") or "").strip()
    repo_path = str(hints.get("repo_path") or "").strip()
    branch = str(hints.get("branch") or "").strip()
    web_file = str(hints.get("web_file") or "").strip()
    expected = str(hints.get("expected_content") or "").strip()
    raw_web_url = str(hints.get("web_url") or "").strip()
    web_url = _local_web_url(raw_web_url)
    prompt_host = str(hints.get("prompt_host") or "").strip()

    messages = [
        f"ssh_user={ssh_user}",
        f"repo_path={repo_path}",
        f"branch={branch}",
        f"web_url={web_url}",
    ]
    problems: list[str] = []
    for key, value in (
        ("ssh_user", ssh_user),
        ("repo_path", repo_path),
        ("branch", branch),
        ("web_file", web_file),
        ("expected_content", expected),
        ("web_url", raw_web_url),
    ):
        if not value:
            problems.append(f"missing required git_webserver_hints.{key}")
    for command in ("git", "ssh", "ssh-keygen"):
        if shutil.which(command) is None:
            problems.append(f"missing required command: {command}")
    if problems:
        return False, messages + problems

    try:
        user_info = pwd.getpwnam(ssh_user)
    except KeyError:
        return False, messages + [f"SSH user does not exist: {ssh_user!r}"]
    repo_check = _run_command(
        ["git", f"--git-dir={repo_path}", "rev-parse", "--is-bare-repository"]
    )
    if repo_check.returncode != 0:
        return False, messages + [
            f"{repo_path} is not a readable bare Git repository: {_command_output(repo_check)}"
        ]

    with tempfile.TemporaryDirectory(prefix="statem-git-webserver-check-") as temp_dir:
        root = Path(temp_dir)
        key_path = root / "id_ed25519"
        problems.extend(_prepare_ssh_key(ssh_user, user_info, key_path))
        if problems:
            return False, messages + problems

        ssh_env = os.environ.copy()
        ssh_env["GIT_SSH_COMMAND"] = (
            f"ssh -i {key_path} -o StrictHostKeyChecking=no "
            "-o UserKnownHostsFile=/dev/null -o BatchMode=yes"
        )
        clone_dir = root / "repo"
        clone_url = f"{ssh_user}@localhost:{repo_path}"
        clone = _run_command(
            ["git", "clone", clone_url, str(clone_dir)],
            env=ssh_env,
            timeout=GATE_TIMEOUT_SECONDS,
        )
        if clone.returncode != 0:
            return False, messages + [
                f"SSH git clone failed for {clone_url}: {_command_output(clone)}"
            ]

        _run_command(["git", "config", "user.email", "statem@example.com"], cwd=clone_dir)
        _run_command(["git", "config", "user.name", "statem deploy check"], cwd=clone_dir)
        target_path = clone_dir / web_file
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(expected + "\n", encoding="utf-8")
        probe_name = f".statem-deploy-check-{int(time.time())}-{os.getpid()}.txt"
        probe_path = clone_dir / probe_name
        probe_path.write_text("statem git webserver deployment check\n", encoding="utf-8")

        add = _run_command(["git", "add", web_file, probe_name], cwd=clone_dir)
        if add.returncode != 0:
            return False, messages + [f"git add failed in SSH clone: {_command_output(add)}"]
        commit = _run_command(
            ["git", "commit", "-m", "statem git webserver deployment check"],
            cwd=clone_dir,
        )
        if commit.returncode != 0:
            return False, messages + [
                f"git commit failed in SSH clone: {_command_output(commit)}"
            ]
        push = _run_command(
            ["git", "push", "origin", f"HEAD:{branch}"],
            cwd=clone_dir,
            env=ssh_env,
            timeout=GATE_TIMEOUT_SECONDS,
        )
        if push.returncode != 0:
            return False, messages + [f"git push over SSH failed: {_command_output(push)}"]

        body_problem = _wait_for_http_body(web_url, expected)
        if body_problem:
            return False, messages + [body_problem]

        cleanup = _run_command(["git", "rm", "--ignore-unmatch", probe_name], cwd=clone_dir)
        if cleanup.returncode != 0:
            return False, messages + [f"git cleanup failed: {_command_output(cleanup)}"]
        cleanup_status = _run_command(["git", "status", "--porcelain"], cwd=clone_dir)
        if cleanup_status.returncode != 0:
            return False, messages + [
                f"git cleanup status failed: {_command_output(cleanup_status)}"
            ]
        if cleanup_status.stdout.strip():
            cleanup_commit = _run_command(
                ["git", "commit", "-m", "statem git webserver deployment check cleanup"],
                cwd=clone_dir,
            )
            if cleanup_commit.returncode != 0:
                return False, messages + [
                    f"git cleanup commit failed: {_command_output(cleanup_commit)}"
                ]
            cleanup_push = _run_command(
                ["git", "push", "origin", f"HEAD:{branch}"],
                cwd=clone_dir,
                env=ssh_env,
                timeout=GATE_TIMEOUT_SECONDS,
            )
            if cleanup_push.returncode != 0:
                return False, messages + [
                    f"git cleanup push failed: {_command_output(cleanup_push)}"
                ]
            body_problem = _wait_for_http_body(web_url, expected)
            if body_problem:
                return False, messages + [f"post-cleanup web check failed: {body_problem}"]
            messages.append("temporary deploy probe cleaned")

        if raw_web_url != web_url and _host_resolves(_url_host(raw_web_url)):
            prompt_problem = _wait_for_http_body(raw_web_url, expected, attempts=3)
            if prompt_problem:
                return False, messages + [f"prompt URL check failed: {prompt_problem}"]
        elif prompt_host and prompt_host not in {"localhost", "127.0.0.1"}:
            messages.append(
                f"prompt_host={prompt_host} was not resolvable; localhost service check was used"
            )
    return True, messages + ["git_webserver_deploy_check passed"]


def _prepare_ssh_key(
    ssh_user: str,
    user_info: pwd.struct_passwd,
    key_path: Path,
) -> list[str]:
    keygen = _run_command(["ssh-keygen", "-t", "ed25519", "-f", str(key_path), "-N", "", "-q"])
    if keygen.returncode != 0:
        return [f"ssh-keygen failed: {_command_output(keygen)}"]
    ssh_dir = Path(user_info.pw_dir) / ".ssh"
    authorized_keys = ssh_dir / "authorized_keys"
    try:
        ssh_dir.mkdir(parents=True, exist_ok=True)
        public_key = key_path.with_suffix(".pub").read_text(encoding="utf-8").strip()
        existing = (
            authorized_keys.read_text(encoding="utf-8", errors="ignore")
            if authorized_keys.exists()
            else ""
        )
        added_key = public_key not in {line.strip() for line in existing.splitlines()}
        if added_key:
            with authorized_keys.open("a", encoding="utf-8") as handle:
                if existing and not existing.endswith("\n"):
                    handle.write("\n")
                handle.write(public_key + "\n")
        os.chown(ssh_dir, user_info.pw_uid, user_info.pw_gid)
        os.chown(authorized_keys, user_info.pw_uid, user_info.pw_gid)
        ssh_dir.chmod(0o700)
        authorized_keys.chmod(0o600)
        if added_key:
            atexit.register(
                _remove_authorized_key,
                authorized_keys,
                public_key,
                user_info.pw_uid,
                user_info.pw_gid,
            )
    except OSError as exc:
        return [f"could not authorize SSH key for {ssh_user}: {exc}"]
    return []


def _remove_authorized_key(
    authorized_keys: Path,
    public_key: str,
    uid: int,
    gid: int,
) -> None:
    try:
        if not authorized_keys.exists():
            return
        remaining = [
            line
            for line in authorized_keys.read_text(encoding="utf-8", errors="ignore").splitlines()
            if line.strip() != public_key
        ]
        payload = "\n".join(remaining)
        authorized_keys.write_text(payload + ("\n" if payload else ""), encoding="utf-8")
        os.chown(authorized_keys, uid, gid)
        authorized_keys.chmod(0o600)
    except OSError:
        return


def _wait_for_http_body(url: str, expected: str, attempts: int = 12) -> str | None:
    last_error = ""
    for _ in range(attempts):
        _, body, error = _observe_url(url)
        if not error and body == expected:
            return None
        last_error = error or f"{url} returned {body!r}, expected {expected!r}"
        time.sleep(1)
    return last_error or f"{url} did not return expected content"


def _observe_url(url: str) -> tuple[str, str, str]:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            status = int(getattr(response, "status", 200))
            body = response.read().decode("utf-8", errors="replace").rstrip("\r\n")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        return url, "", f"{url} request failed: {exc}"
    if status != 200:
        return url, body, f"{url} returned HTTP {status}"
    return url, body, ""


def _host_resolves(host: str) -> bool:
    if not host:
        return False
    try:
        socket.getaddrinfo(host, None)
    except OSError:
        return False
    return True


def _url_host(url: str) -> str:
    try:
        return urllib.parse.urlparse(url).hostname or ""
    except ValueError:
        return ""


def _run_command(
    command: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: float = 30,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(
            command,
            124,
            exc.stdout or "",
            (exc.stderr or "") + f"\ntimed out after {timeout:g}s",
        )


def _command_output(completed: subprocess.CompletedProcess[str]) -> str:
    return "\n".join(
        part.strip() for part in (completed.stdout, completed.stderr) if part.strip()
    )[:2000]


def _branch_head(hints: Any) -> str:
    if not isinstance(hints, dict):
        return ""
    repo_path = str(hints.get("repo_path") or "").strip()
    branch = str(hints.get("branch") or "").strip()
    if not repo_path or not branch:
        return ""
    try:
        completed = subprocess.run(
            ["git", f"--git-dir={repo_path}", "rev-parse", f"refs/heads/{branch}"],
            capture_output=True,
            check=False,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return completed.stdout.strip() if completed.returncode == 0 else ""


def _observe_http(hints: Any) -> tuple[str, str, str]:
    if not isinstance(hints, dict):
        return "", "", "missing git webserver hints"
    raw_url = str(hints.get("web_url") or "").strip()
    if not raw_url:
        return "", "", "missing consumer HTTP URL"
    url = _local_web_url(raw_url)
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            status = int(getattr(response, "status", 200))
            body = response.read().decode("utf-8", errors="replace").rstrip("\r\n")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        return url, "", f"current HTTP request failed: {exc}"
    if status != 200:
        return url, body, f"current HTTP request returned status {status}"
    return url, body, ""


def _local_web_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return url
    if parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
        return url
    netloc = "localhost" + (f":{parsed.port}" if parsed.port else "")
    return urllib.parse.urlunparse(parsed._replace(netloc=netloc))


def _meaningful(value: Any, *, minimum: int = 4) -> bool:
    if isinstance(value, dict):
        return any(_meaningful(item, minimum=minimum) for item in value.values())
    if isinstance(value, list):
        return any(_meaningful(item, minimum=minimum) for item in value)
    return len(str(value or "").strip()) >= minimum


def _has_open_items(value: Any) -> bool:
    if not isinstance(value, list):
        return False
    for item in value:
        if isinstance(item, dict):
            status = str(item.get("status") or "open").strip().lower()
            if status not in {"fixed", "resolved", "not_applicable"} and _meaningful(item):
                return True
        elif _meaningful(item):
            return True
    return False


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _raise_errors(problems: list[str]) -> None:
    if problems:
        raise ValueError("; ".join(problems))


def _print_errors(problems: list[str]) -> int:
    for problem in problems:
        print(problem)
    return 1 if problems else 0


def deadline_status(path: Path, *, now: float | None = None) -> dict[str, Any]:
    try:
        payload = _read_json(path)
    except (OSError, json.JSONDecodeError):
        payload = {}
    if not isinstance(payload, dict) or not payload.get("deadline_at_epoch"):
        return {
            "configured": False,
            "mode": "unbounded",
            "remaining_seconds": None,
        }
    current = time.time() if now is None else now
    deadline_at = _as_float(payload.get("deadline_at_epoch"))
    if deadline_at is None:
        return {
            "configured": False,
            "mode": "unbounded",
            "remaining_seconds": None,
        }
    handoff_buffer = _positive_int(payload.get("handoff_buffer_seconds"), 120)
    heavy_buffer = _positive_int(payload.get("heavy_work_buffer_seconds"), 240)
    remaining = int(deadline_at - current)
    if remaining <= 0:
        mode = "expired"
    elif remaining <= handoff_buffer:
        mode = "handoff_due"
    elif remaining <= heavy_buffer:
        mode = "heavy_work_closed"
    else:
        mode = "normal"
    return {
        "configured": True,
        "mode": mode,
        "remaining_seconds": remaining,
        "handoff_buffer_seconds": handoff_buffer,
        "heavy_work_buffer_seconds": heavy_buffer,
    }


def validate_deadline_predicate(
    status: dict[str, Any],
    *,
    required_modes: set[str] | None = None,
    min_remaining: int | None = None,
    handoff_due_or_expired: bool = False,
    heavy_work_closed_or_worse: bool = False,
) -> list[str]:
    if not status.get("configured"):
        return []
    mode = str(status.get("mode") or "")
    remaining = status.get("remaining_seconds")
    problems: list[str] = []
    if required_modes and mode not in required_modes:
        problems.append(f"deadline mode {mode!r} is not one of {sorted(required_modes)!r}")
    if min_remaining is not None and isinstance(remaining, int) and remaining < min_remaining:
        problems.append(
            f"deadline remaining_seconds={remaining} is below required {min_remaining}"
        )
    if handoff_due_or_expired and mode not in {"handoff_due", "expired"}:
        problems.append("deadline is not handoff_due or expired")
    if heavy_work_closed_or_worse and mode not in {
        "heavy_work_closed",
        "handoff_due",
        "expired",
    }:
        problems.append("deadline has not closed heavy work")
    return problems


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Standalone git_webserver_deploy family router, reviewer, and receipt gate."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    select_parser = subparsers.add_parser("select")
    select_parser.add_argument("--task", type=Path, default=DEFAULT_TASK)
    select_parser.add_argument("--selection", type=Path, default=DEFAULT_SELECTION)
    select_parser.add_argument("--quiet", action="store_true")

    for name in ("validate-selection", "render-practice"):
        command = subparsers.add_parser(name)
        command.add_argument("--task", type=Path, default=DEFAULT_TASK)
        command.add_argument("--selection", type=Path, default=DEFAULT_SELECTION)

    route_parser = subparsers.add_parser("route")
    route_parser.add_argument("--task", type=Path, default=DEFAULT_TASK)
    route_parser.add_argument("--selection", type=Path, default=DEFAULT_SELECTION)
    route_parser.add_argument("--target", choices=("family_evidence", "handoff"), required=True)

    contract_init = subparsers.add_parser("init-contract")
    contract_init.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    contract_check = subparsers.add_parser("validate-contract")
    contract_check.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    contract_status = subparsers.add_parser("contract-status")
    contract_status.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    contract_status.add_argument("--status", choices=("passed", "failed"), required=True)

    review_init = subparsers.add_parser("init-review")
    review_init.add_argument("--task", type=Path, default=DEFAULT_TASK)
    review_init.add_argument("--selection", type=Path, default=DEFAULT_SELECTION)
    review_init.add_argument("--review", type=Path, default=DEFAULT_REVIEW)
    review_check = subparsers.add_parser("validate-review")
    review_check.add_argument("--task", type=Path, default=DEFAULT_TASK)
    review_check.add_argument("--selection", type=Path, default=DEFAULT_SELECTION)
    review_check.add_argument("--review", type=Path, default=DEFAULT_REVIEW)
    review_status = subparsers.add_parser("review-status")
    review_status.add_argument("--task", type=Path, default=DEFAULT_TASK)
    review_status.add_argument("--selection", type=Path, default=DEFAULT_SELECTION)
    review_status.add_argument("--review", type=Path, default=DEFAULT_REVIEW)
    review_status.add_argument(
        "--target", choices=("repair", "family_evidence", "handoff", "deadline_handoff"), required=True
    )

    gate_run = subparsers.add_parser("run-gate")
    gate_run.add_argument("--task", type=Path, default=DEFAULT_TASK)
    gate_run.add_argument("--selection", type=Path, default=DEFAULT_SELECTION)
    gate_run.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    receipt_check = subparsers.add_parser("validate-receipt")
    receipt_check.add_argument("--task", type=Path, default=DEFAULT_TASK)
    receipt_check.add_argument("--selection", type=Path, default=DEFAULT_SELECTION)
    receipt_check.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    receipt_check.add_argument("--max-age-seconds", type=int, default=900)
    receipt_status = subparsers.add_parser("receipt-status")
    receipt_status.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    receipt_status.add_argument("--status", choices=("passed", "failed"), required=True)

    deadline_parser = subparsers.add_parser("deadline")
    deadline_parser.add_argument("--deadline", type=Path, default=DEFAULT_DEADLINE)
    deadline_parser.add_argument("--require-mode", default="")
    deadline_parser.add_argument("--min-remaining", type=int)
    deadline_parser.add_argument("--handoff-due-or-expired", action="store_true")
    deadline_parser.add_argument("--heavy-work-closed-or-worse", action="store_true")

    args = parser.parse_args(argv)
    try:
        if args.command == "select":
            selected = select_family(_read_text(args.task))
            if args.selection.exists():
                _raise_errors(validate_selection(_read_json(args.selection), _read_text(args.task)))
            else:
                _write_json(args.selection, selected)
            if not args.quiet:
                print(json.dumps(selected, indent=2, sort_keys=True))
            return 0
        if args.command in {"validate-selection", "render-practice", "route"}:
            task_text = _read_text(args.task)
            selection = _read_json(args.selection)
            problems = validate_selection(selection, task_text)
            if problems:
                return _print_errors(problems)
            if args.command == "validate-selection":
                print("git_webserver_deploy selection is valid")
                return 0
            if args.command == "render-practice":
                rendered = render_practice(selection, task_text)
                if rendered:
                    print(rendered)
                return 0
            expected_selected = args.target == "family_evidence"
            return 0 if bool(selection["selected"]) == expected_selected else 1
        if args.command == "init-contract":
            _write_json(args.contract, initial_contract())
            return 0
        if args.command in {"validate-contract", "contract-status"}:
            contract = _read_json(args.contract)
            problems = validate_contract(contract)
            if problems:
                return _print_errors(problems)
            if args.command == "validate-contract":
                print("task contract receipt is valid")
                return 0
            return 0 if contract.get("status") == args.status else 1
        if args.command == "init-review":
            selection = _read_json(args.selection)
            _raise_errors(validate_selection(selection, _read_text(args.task)))
            _write_json(args.review, initial_review(selection))
            return 0
        if args.command in {"validate-review", "review-status"}:
            task_text = _read_text(args.task)
            selection = _read_json(args.selection)
            review = _read_json(args.review)
            problems = validate_review(review, selection, task_text)
            if problems:
                return _print_errors(problems)
            if args.command == "validate-review":
                print("bounded self-review is valid")
                return 0
            status = review.get("status")
            allowed = {
                "repair": {"issues_found"},
                "family_evidence": {"clean", "needs_evidence"},
                "handoff": {"clean"},
                "deadline_handoff": {"deadline_handoff"},
            }[args.target]
            return 0 if status in allowed else 1
        if args.command == "run-gate":
            passed, receipt = run_gate(
                _read_json(args.selection), _read_text(args.task), args.receipt
            )
            for message in receipt["messages"]:
                print(message)
            return 0 if passed else 1
        if args.command == "validate-receipt":
            problems = validate_receipt(
                _read_json(args.receipt),
                _read_json(args.selection),
                _read_text(args.task),
                max_age_seconds=args.max_age_seconds,
            )
            if problems:
                return _print_errors(problems)
            print("git_webserver_deploy receipt is current and valid")
            return 0
        if args.command == "receipt-status":
            try:
                status = str(_read_json(args.receipt).get("status") or "failed")
            except (OSError, json.JSONDecodeError, AttributeError):
                status = "failed"
            return 0 if status == args.status else 1
        if args.command == "deadline":
            status = deadline_status(args.deadline)
            print(
                "deadline_status "
                f"mode={status.get('mode')} "
                f"remaining_seconds={status.get('remaining_seconds')} "
                f"configured={str(bool(status.get('configured'))).lower()}"
            )
            required_modes = {
                item.strip()
                for item in str(args.require_mode or "").split(",")
                if item.strip()
            }
            return _print_errors(
                validate_deadline_predicate(
                    status,
                    required_modes=required_modes,
                    min_remaining=args.min_remaining,
                    handoff_due_or_expired=args.handoff_due_or_expired,
                    heavy_work_closed_or_worse=args.heavy_work_closed_or_worse,
                )
            )
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        print(f"git_webserver_deploy family error: {exc}")
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
