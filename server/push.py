"""Web-push delivery (spec sub-project 4). Subscriptions live in
<vault>/.sidekick-push.json — gitignored runtime state, like the idempotency
store — mapping identity name → list of browser PushSubscription dicts.
Sending prunes subscriptions the push service reports gone (404/410); other
per-subscription failures are skipped (best-effort — a nudge is a nudge, not
an alarm). VAPID keys come from the environment. This module is deliberately
GENERAL (any identity can be stored and addressed); ROUTING — who actually
gets nudged — is the caller's decision (server/nudge_job.py: dalton only this
phase). Store mutations hold the vault lock: the API's subscribe handler and
the nudge job's pruning may run in different processes."""
import json
import os

from pywebpush import webpush, WebPushException

from server.vault_lock import vault_lock

STORE_NAME = ".sidekick-push.json"


def store_path(vault):
    return os.path.join(vault, STORE_NAME)


def _load(vault):
    try:
        with open(store_path(vault), encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(vault, data):
    tmp = store_path(vault) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, store_path(vault))


def save_subscription(vault, name, sub):
    """Store one browser PushSubscription for an identity. Re-subscribing from
    the same browser (same endpoint) replaces, not duplicates. Returns the
    identity's subscription count."""
    with vault_lock(vault):
        data = _load(vault)
        subs = [s for s in data.get(name, []) if s.get("endpoint") != sub.get("endpoint")]
        subs.append(sub)
        data[name] = subs
        _save(vault, data)
        return len(subs)


def _vapid_env():
    """(private_key, claims_sub) from the environment, or None when push isn't set up."""
    priv = os.environ.get("SIDEKICK_VAPID_PRIVATE", "")
    sub = os.environ.get("SIDEKICK_VAPID_SUB", "")
    if not priv or not sub:
        return None
    return priv, sub


def send_to_identity(config, name, title, body):
    """Send one notification to every subscription of `name`. Returns the number
    delivered. Raises RuntimeError if VAPID keys are not configured."""
    env = _vapid_env()
    if env is None:
        raise RuntimeError(
            "web push not configured (set SIDEKICK_VAPID_PRIVATE / SIDEKICK_VAPID_SUB)")
    priv, claims_sub = env
    with vault_lock(config.vault):
        subs = _load(config.vault).get(name, [])
    payload = json.dumps({"title": title, "body": body})
    delivered, gone = 0, []
    for sub in subs:
        try:
            webpush(subscription_info=sub, data=payload,
                    vapid_private_key=priv,
                    vapid_claims={"sub": claims_sub})  # fresh dict: pywebpush mutates it
            delivered += 1
        except WebPushException as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status in (404, 410):
                gone.append(sub.get("endpoint"))
            # anything else: skip this subscription, keep going (best-effort)
    if gone:
        with vault_lock(config.vault):
            data = _load(config.vault)
            data[name] = [s for s in data.get(name, []) if s.get("endpoint") not in gone]
            _save(config.vault, data)
    return delivered
