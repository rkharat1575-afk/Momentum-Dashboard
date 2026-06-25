"""
╔══════════════════════════════════════════════════════════════════╗
║   SHAREKHAN API — DAILY LOGIN SCRIPT (AUDITED v2.0)             ║
║   Run this EVERY MORNING before 9:15 AM                         ║
╚══════════════════════════════════════════════════════════════════╝

VERIFIED AGAINST ACTUAL SOURCE CODE of shareconnect v1.0.0.11

AUDIT NOTES:
  - get_access_token() returns a DICT (not a plain string)
  - generate_session_without_versionId() requires pycryptodome + cryptography
  - Access token string must be extracted from the response dict
  - Without pycryptodome/cryptography the session step crashes

INSTALL (run once):
    pip install shareconnect websocket-client pycryptodome cryptography six
    (ALL of these are required - missing any will crash)

USAGE: python daily_login.py
"""

import os
import sys
import json
import webbrowser

# Helper to load .env manually if python-dotenv is not installed
if os.path.exists(".env"):
    with open(".env") as f:
        for line in f:
            if line.strip() and not line.strip().startswith("#") and "=" in line:
                key, val = line.strip().split("=", 1)
                os.environ[key.strip()] = val.strip()

# ── YOUR CREDENTIALS ──────────────────────────────────────────────
API_KEY    = os.environ.get("SHAREKHAN_API_KEY", "")        # From Sharekhan API portal
SECRET_KEY = os.environ.get("SHAREKHAN_SECRET_KEY", "")     # From Sharekhan API portal
STATE      = 12345                      # Any integer - CSRF protection, keep as is
# ─────────────────────────────────────────────────────────────────

OUTPUT_FILE = "access_token.txt"
RESPONSE_FILE = "last_token_response.json"  # Full response saved for debugging


def check_dependencies():
    """Verify all required packages are installed before proceeding."""
    missing = []
    packages = {
        "SharekhanApi": "shareconnect",
        "websocket": "websocket-client",
        "Crypto": "pycryptodome",
        "cryptography": "cryptography",
        "six": "six",
    }
    for module, pip_name in packages.items():
        try:
            __import__(module)
        except ImportError:
            missing.append(pip_name)

    if missing:
        print("=" * 60)
        print("  MISSING REQUIRED PACKAGES — INSTALL THESE FIRST:")
        print("=" * 60)
        print(f"\n  pip install {' '.join(missing)}\n")
        print("  Or install all at once:")
        print("  pip install shareconnect websocket-client pycryptodome cryptography six")
        print()
        sys.exit(1)

    print("✅ All dependencies verified.")


def extract_access_token(response):
    """
    Extract the access token STRING from the API response dict.
    
    The get_access_token() method returns a dict (full JSON response),
    NOT a plain string. This function handles multiple possible key names.
    
    Verified from source: get_access_token() calls _postRequest() which
    returns json.loads(r.content.decode("utf8")) — a dict.
    """
    if isinstance(response, str):
        # Already a string — return directly
        return response.strip()

    if not isinstance(response, dict):
        print(f"⚠ Unexpected response type: {type(response)}")
        print(f"  Raw value: {response}")
        return None

    # Try all known key patterns (Sharekhan may use any of these)
    candidate_keys = [
        "accessToken",      # Most common pattern
        "access_token",     # Snake case variant
        "AccessToken",      # PascalCase variant
        "token",            # Short form
        "Token",
    ]

    # Direct key check
    for key in candidate_keys:
        val = response.get(key)
        if val and isinstance(val, str) and len(val) > 10:
            return val.strip()

    # Nested under "data" key
    data = response.get("data") or response.get("Data")
    if isinstance(data, dict):
        for key in candidate_keys:
            val = data.get(key)
            if val and isinstance(val, str) and len(val) > 10:
                return val.strip()

    # Last resort: find any long string value in the dict
    print("\n⚠  Could not find access token with known key names.")
    print("   Full response dict:")
    for k, v in response.items():
        print(f"   [{k}]: {repr(v)[:80]}")
    print()
    print("   Please check above and identify the key containing your access token.")
    print("   Then edit this script and add that key to 'candidate_keys' list.")
    return None


def main():
    print("=" * 60)
    print("  SHAREKHAN API — DAILY LOGIN (AUDITED v2.0)")
    print("=" * 60)

    # Step 0: Check all dependencies
    check_dependencies()

    # Smart Daily Login: Skip if token is from today
    if os.path.exists(OUTPUT_FILE):
        try:
            from datetime import date
            mtime = os.path.getmtime(OUTPUT_FILE)
            file_date = date.fromtimestamp(mtime)
            if file_date == date.today():
                print(f"\n✅ Found existing access token from today in {OUTPUT_FILE}.")
                print("   Skipping login process since the token is valid for the entire day!")
                print("   You can proceed directly to starting the terminal.")
                sys.exit(0)
        except Exception as e:
            print(f"⚠ Could not verify token age: {e}")

    # Late import after dependency check
    from SharekhanApi.sharekhanConnect import SharekhanConnect

    # Validate credentials are set
    if API_KEY == "YOUR_API_KEY_HERE" or SECRET_KEY == "YOUR_SECRET_KEY_HERE":
        print("\n❌ ERROR: You must set API_KEY and SECRET_KEY in this file first!")
        print("   Open daily_login.py and edit lines 25-26 with your actual keys.")
        sys.exit(1)

    # Step 1: Generate Login URL
    print("\n[STEP 1/4] Generating login URL...")

    login = SharekhanConnect(api_key=API_KEY)

    # login_url() signature: login_url(vendor_key=None, version_id=None)
    # For personal accounts: vendor_key=None, version_id=None
    url = login.login_url(vendor_key=None, version_id=None)

    print(f"\n📎 Login URL:\n{url}\n")
    print("Opening in browser...")
    try:
        webbrowser.open(url)
    except Exception:
        print("(Could not open browser automatically — copy the URL above manually)")

    print("\n[STEP 2/4] Login in browser:")
    print("  1. Log in with your Sharekhan credentials")
    print("  2. Complete OTP / 2FA")
    print("  3. After login, browser redirects to a URL like:")
    print("     https://redirect.url?request_token=XXXXXXXXXXX&state=12345")
    print("  4. Copy the request_token value from that redirect URL")
    print()

    request_token = input("Paste request_token here: ").strip()
    if not request_token:
        print("❌ No token entered. Exiting.")
        sys.exit(1)

    # Step 3: Generate session (decrypt + re-encrypt request token)
    print("\n[STEP 3/4] Generating session (AES decrypt/encrypt)...")
    print("  Using: generate_session_without_versionId(request_token, secret_key)")

    try:
        # AUDITED: This method uses pycryptodome (AES.MODE_GCM) + cryptography
        # It decrypts the request_token, swaps RequestId|CustomerId format,
        # then re-encrypts. Requires SECRET_KEY to be exactly 32 bytes.
        if len(SECRET_KEY) != 32:
            print(f"\n⚠  WARNING: SECRET_KEY is {len(SECRET_KEY)} characters.")
            print("   It should be exactly 32 characters for AES-256.")
            print("   If this step fails, check your secret key length.")

        session = login.generate_session_without_versionId(request_token, SECRET_KEY)
        print("✅ Session generated.")
    except ValueError as e:
        if "Invalid key size" in str(e):
            print(f"\n❌ SECRET KEY ERROR: {e}")
            print("   Your SECRET_KEY must be exactly 32 characters long.")
            print(f"   Current length: {len(SECRET_KEY)}")
            sys.exit(1)
        raise
    except Exception as e:
        print(f"\n❌ Session generation failed: {type(e).__name__}: {e}")
        print("\nCommon causes:")
        print("  - request_token already used (each token is one-time use only)")
        print("  - Wrong secret key")
        print("  - request_token was copy-pasted with extra spaces")
        sys.exit(1)

    # Step 4: Get access token
    print("\n[STEP 4/4] Fetching access token from Sharekhan API...")
    print("  POST /skapi/services/access/token")

    try:
        # AUDITED SIGNATURE: get_access_token(self, apiKey, encstr, state, vendorkey=None, versionId=None)
        # Returns: dict (full JSON response) — NOT a plain string
        response = login.get_access_token(API_KEY, session, STATE)
    except Exception as e:
        print(f"\n❌ Access token request failed: {type(e).__name__}: {e}")
        sys.exit(1)

    # Save full response for debugging
    with open(RESPONSE_FILE, "w") as f:
        json.dump(response, f, indent=2)
    print(f"   Full API response saved to {RESPONSE_FILE} (for debugging)")

    # CRITICAL: Extract the token string from the dict response
    access_token = extract_access_token(response)

    if not access_token:
        print("\n❌ Could not extract access token from response.")
        print(f"   Check {RESPONSE_FILE} to see the full response.")
        print("   Identify which key contains the token and update extract_access_token()")
        sys.exit(1)

    # Save the token string to file
    with open(OUTPUT_FILE, "w") as f:
        f.write(access_token)

    # Also save full response
    print(f"\n{'=' * 60}")
    print(f"  ✅ ACCESS TOKEN SAVED TO: {OUTPUT_FILE}")
    print(f"  Token preview: {access_token[:30]}...")
    print(f"  Token length: {len(access_token)} characters")
    print(f"{'=' * 60}")
    print()
    print("You can now run the trading terminal:")
    print("  streamlit run sharekhan_terminal.py")
    print()
    print("⚠  IMPORTANT NOTES:")
    print("  - This token is valid for ONE trading session only")
    print("  - Run this script again tomorrow morning before 9:15 AM")
    print("  - Do NOT share your access_token.txt file")


if __name__ == "__main__":
    main()
