"""Pre-approved, allow-listed printer automations (simulated remote actions)."""

import random

AUTOMATIONS = {
    "restart_print_spooler": "Restarted Windows Print Spooler service on the POS terminal",
    "clear_print_queue": "Cleared stuck jobs from the printer queue",
    "send_test_print": "Sent a test receipt to the printer",
}


def run_automation(name: str, asset_id: str | None) -> dict:
    if name not in AUTOMATIONS:
        return {"ok": False, "message": f"'{name}' is not on the automation allow-list — blocked"}
    # Simulated: deterministic per asset so demos are repeatable
    ok = random.Random(f"{name}:{asset_id}").random() > 0.15
    return {
        "ok": ok,
        "message": f"{AUTOMATIONS[name]} (asset {asset_id or 'n/a'}): "
        + ("completed successfully" if ok else "device did not respond — follow manual steps"),
    }
