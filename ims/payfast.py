"""PayFast payment gateway utilities for Rehumile IMS."""
import hashlib
import urllib.parse
import logging
import requests as http_requests

logger = logging.getLogger(__name__)

# ── Sandbox credentials ───────────────────────────────────────────────────────
PAYFAST_MERCHANT_ID = '10000100'
PAYFAST_MERCHANT_KEY = '46f0cd694581a'
PAYFAST_PASSPHRASE = ''        # Set after adding passphrase in PayFast portal
PAYFAST_SANDBOX = True

PAYFAST_PROCESS_URL = (
    'https://sandbox.payfast.co.za/eng/process'
    if PAYFAST_SANDBOX else
    'https://www.payfast.co.za/eng/process'
)
PAYFAST_VALIDATE_URL = (
    'https://sandbox.payfast.co.za/eng/query/validate'
    if PAYFAST_SANDBOX else
    'https://www.payfast.co.za/eng/query/validate'
)


def generate_signature(data: dict, passphrase: str = None) -> str:
    """Generate PayFast MD5 signature from sorted, URL-encoded payload."""
    # Exclude empty values and the signature field itself
    filtered = {k: v for k, v in data.items() if str(v).strip() != '' and k != 'signature'}
    payload = '&'.join(
        f"{k}={urllib.parse.quote_plus(str(v))}"
        for k, v in sorted(filtered.items())
    )
    if passphrase:
        payload += f"&passphrase={urllib.parse.quote_plus(passphrase)}"
    return hashlib.md5(payload.encode('utf-8')).hexdigest()


def build_payment_data(
    reference: str,
    amount: float,
    item_name: str,
    first_name: str = '',
    last_name: str = '',
    email: str = '',
    return_url: str = '',
    cancel_url: str = '',
    notify_url: str = '',
) -> dict:
    """Build the PayFast POST data dict including signature."""
    data = {
        'merchant_id': PAYFAST_MERCHANT_ID,
        'merchant_key': PAYFAST_MERCHANT_KEY,
        'return_url': return_url,
        'cancel_url': cancel_url,
        'notify_url': notify_url,
        'name_first': first_name,
        'name_last': last_name,
        'email_address': email,
        'm_payment_id': reference,
        'amount': f"{float(amount):.2f}",
        'item_name': item_name[:100],
    }
    passphrase = PAYFAST_PASSPHRASE if PAYFAST_PASSPHRASE else None
    data['signature'] = generate_signature(data, passphrase)
    return data


def validate_itn(post_data: dict) -> tuple[bool, str]:
    """Validate a PayFast ITN (Instant Transaction Notification).
    Returns (is_valid, reason).
    """
    received_sig = post_data.get('signature', '')

    # 1. Rebuild signature from received data
    check_data = {k: v for k, v in post_data.items() if k != 'signature'}
    passphrase = PAYFAST_PASSPHRASE if PAYFAST_PASSPHRASE else None
    expected_sig = generate_signature(check_data, passphrase)

    if received_sig != expected_sig:
        logger.warning("PayFast ITN signature mismatch: expected=%s got=%s", expected_sig, received_sig)
        return False, 'signature_mismatch'

    # 2. Server-side validation with PayFast
    try:
        resp = http_requests.post(
            PAYFAST_VALIDATE_URL,
            data=post_data,
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
            timeout=15,
        )
        if resp.text.strip() != 'VALID':
            logger.warning("PayFast validation returned: %s", resp.text)
            return False, 'pf_invalid'
    except Exception as exc:
        logger.error("PayFast validation request failed: %s", exc)
        # In sandbox allow through on network error so we can test
        if PAYFAST_SANDBOX:
            logger.warning("Sandbox mode — skipping PF validation due to network error")
        else:
            return False, f'network_error: {exc}'

    return True, 'ok'
