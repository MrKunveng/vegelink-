"""Pluggable SMS sender.

Single integration point for a real SMS / USSD gateway. The project ships
Africa's-Talking-compatible (the USSD endpoint already speaks CON/END), so the
natural live provider is Africa's Talking, but any HTTP SMS API drops in here.

With no credentials configured it runs in SIMULATED mode: messages are only
recorded in the in-app activity feed (the existing behaviour), so the demo works
offline. Set the env vars below to send real SMS without changing any caller.

    SMS_PROVIDER=africastalking
    AT_USERNAME=...            # Africa's Talking username ('sandbox' for tests)
    AT_API_KEY=...
    AT_SENDER_ID=VegeLink      # optional short code / sender id
"""
import os
import urllib.parse
import urllib.request

SMS_PROVIDER = os.environ.get("SMS_PROVIDER", "simulated")
AT_USERNAME = os.environ.get("AT_USERNAME", "")
AT_API_KEY = os.environ.get("AT_API_KEY", "")
AT_SENDER_ID = os.environ.get("AT_SENDER_ID", "VegeLink")


def sms_enabled():
    return SMS_PROVIDER == "africastalking" and AT_USERNAME and AT_API_KEY


def send_sms(phone, message):
    """Send (or simulate) an SMS. Returns True if a real message was dispatched.
    Never raises into the request path — failures degrade to simulated mode."""
    if not sms_enabled():
        return False
    try:
        data = urllib.parse.urlencode({
            "username": AT_USERNAME,
            "to": phone,
            "message": message,
            "from": AT_SENDER_ID,
        }).encode()
        req = urllib.request.Request(
            "https://api.africastalking.com/version1/messaging",
            data=data,
            headers={
                "apiKey": AT_API_KEY,
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
        )
        urllib.request.urlopen(req, timeout=8).read()
        return True
    except Exception:
        return False  # fall back to the in-app feed silently
