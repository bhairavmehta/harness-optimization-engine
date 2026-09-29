"""GitHub delivery for first-party agents: branch, commits and a pull request.

Live mode needs GITHUB_TOKEN (a token with contents + pull-request write access to
HOE_GITHUB_REPO). Without it every call is a dry run that returns the same links and
the git/gh commands to do it by hand, so a public demo can never write to the repo.

Env: HOE_GITHUB_REPO (owner/name), HOE_GITHUB_BASE (base branch), HOE_GITHUB_PATH
(folder for agent harness files, "{agent}" is substituted), HOE_GITHUB_API (API root).
"""
import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request

REPO = os.environ.get("HOE_GITHUB_REPO", "bhairavmehta/harness-optimization-engine")
BASE = os.environ.get("HOE_GITHUB_BASE", "main")
PATH = os.environ.get("HOE_GITHUB_PATH", "agents/{agent}")
API = os.environ.get("HOE_GITHUB_API", "https://api.github.com").rstrip("/")
WEB = "https://github.com"


def live():
    return bool(os.environ.get("GITHUB_TOKEN"))


# ------------------------------------------------------------------ links
def repo_url():
    return f"{WEB}/{REPO}"


def branch_url(branch):
    return f"{repo_url()}/tree/{urllib.parse.quote(branch, safe='/')}"


def commit_url(sha):
    return f"{repo_url()}/commit/{sha}"


def pr_url(number):
    return f"{repo_url()}/pull/{number}"


def pulls_url():
    return f"{repo_url()}/pulls"


def compare_url(branch):
    return f"{repo_url()}/compare/{BASE}...{urllib.parse.quote(branch, safe='/')}?expand=1"


def file_url(path, ref=None):
    return f"{repo_url()}/blob/{urllib.parse.quote(ref or BASE, safe='/')}/{path}"


def agent_path(agent):
    return PATH.format(agent=agent)


def status():
    return {"repo": REPO, "url": repo_url(), "base": BASE, "live": live(), "pulls": pulls_url()}


# ------------------------------------------------------------------ REST client
class GitHubError(RuntimeError):
    pass


def _call(method, path, body=None, ok_missing=False):
    req = urllib.request.Request(
        f"{API}{path}", method=method, data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}", "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "harness-optimization-engine",
                 **({"Content-Type": "application/json"} if body is not None else {})})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        if ok_missing and e.code == 404:
            return None
        detail = e.read().decode(errors="replace")
        try:
            detail = json.loads(detail).get("message", detail)
        except ValueError:
            pass
        raise GitHubError(f"GitHub {method} {path} failed ({e.code}): {detail}") from None
    except urllib.error.URLError as e:
        raise GitHubError(f"GitHub unreachable: {e.reason}") from None


def _ensure_branch(branch):
    q = urllib.parse.quote(branch, safe="")
    if _call("GET", f"/repos/{REPO}/git/ref/heads/{q}", ok_missing=True):
        return False
    base = _call("GET", f"/repos/{REPO}/git/ref/heads/{urllib.parse.quote(BASE, safe='')}")
    _call("POST", f"/repos/{REPO}/git/refs", {"ref": f"refs/heads/{branch}", "sha": base["object"]["sha"]})
    return True


def _put_file(branch, path, content, message):
    """Create or update one file on the branch; returns the commit sha, or None if unchanged."""
    q = urllib.parse.quote(path)
    cur = _call("GET", f"/repos/{REPO}/contents/{q}?ref={urllib.parse.quote(branch, safe='')}", ok_missing=True)
    encoded = base64.b64encode(content.encode()).decode()
    if cur and cur.get("content", "").replace("\n", "") == encoded:
        return None
    body = {"message": message, "content": encoded, "branch": branch}
    if cur:
        body["sha"] = cur["sha"]
    return _call("PUT", f"/repos/{REPO}/contents/{q}", body)["commit"]["sha"]


def _find_pr(branch):
    owner = REPO.split("/")[0]
    hits = _call("GET", f"/repos/{REPO}/pulls?state=open&head={urllib.parse.quote(f'{owner}:{branch}')}")
    return hits[0] if hits else None


# ------------------------------------------------------------------ pull request
def open_pr(branch, title, body, commits, baseline=None):
    """commits: [(message, {path: content}), ...] applied in order on `branch`, then a PR to BASE.
    baseline: an optional (message, files) committed first, only when the branch is new, so the
    fix commit shows the exact change. Re-running on an up-to-date branch makes no commits.
    Returns links plus, in live mode, the PR number and the commits that were made."""
    everything = ([baseline] if baseline else []) + list(commits)
    out = {"repo": REPO, "repo_url": repo_url(), "base": BASE, "branch": branch, "branch_url": branch_url(branch),
           "compare_url": compare_url(branch), "live": live(),
           "files": sorted({p for _, files in everything for p in files}),
           "file_urls": {p: file_url(p, branch) for _, files in everything for p in files}}
    if not live():
        out["commands"] = _manual_commands(branch, title, everything)
        out["note"] = "Dry run: set GITHUB_TOKEN on the server to create the branch, commits and pull request."
        return out
    created = _ensure_branch(branch)
    made = []
    for message, files in ([baseline] if baseline and created else []) + list(commits):
        for path, content in files.items():
            sha = _put_file(branch, path, content, message)
            if sha:
                made.append({"sha": sha, "short": sha[:7], "message": message, "url": commit_url(sha)})
    pr = _find_pr(branch)
    reused = bool(pr)
    if not pr:
        pr = _call("POST", f"/repos/{REPO}/pulls", {"title": title, "head": branch, "base": BASE, "body": body})
    out.update(branch_created=created, commits=made, pr_number=pr["number"], pr_url=pr["html_url"], pr_reused=reused)
    return out


def _manual_commands(branch, title, commits):
    lines = [f"git clone {repo_url()}.git", f"cd {REPO.split('/')[1]}", f"git checkout -b {branch} origin/{BASE}"]
    for message, files in commits:
        lines.append(f"# write: {', '.join(files)}")
        lines.append(f"git add {' '.join(files)} && git commit -m \"{message}\"")
    lines += [f"git push -u origin {branch}", f"gh pr create --base {BASE} --head {branch} --title \"{title}\" --body-file pr-body.md"]
    return "\n".join(lines)
