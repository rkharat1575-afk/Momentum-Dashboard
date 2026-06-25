"""
daily_login.py — Run this EVERY MORNING before 9:15 AM
to generate your access token for the trading session.

Usage: python daily_login.py
"""

from SharekhanApi.sharekhanConnect import SharekhanConnect
import webbrowser

# ── YOUR CREDENTIALS ──────────────────────────────────────────────
API_KEY    = "YOUR_API_KEY_HERE"        # Replace with your API Key
SECRET_KEY = "YOUR_SECRET_KEY_HERE"     # Replace with your Secret Key
STATE      = 12345                      # Any integer (CSRF protection)
VERSION_ID = None                       # Leave None for personal account
VENDOR_KEY = ""                         # Leave blank for personal account
# ─────────────────────────────────────────────────────────────────


def main():
    print("=" * 60)
    print("  SHAREKHAN API — DAILY LOGIN")
    print("=" * 60)

    # Step 1: Generate Login URL
    login = SharekhanConnect(API_KEY)
    url = login.login_url(vendor_key=VENDOR_KEY, version_id=VERSION_ID)

    print(f"\n[STEP 1] Opening login URL in browser...")
    print(f"URL: {url}\n")

    try:
        webbrowser.open(url)
        print("Browser opened! Please log in with your Sharekhan credentials + OTP.")
    except Exception:
        print("Could not open browser automatically. Please copy the URL above and open manually.")

    print("\n[STEP 2] After login, you'll be redirected to a URL like:")
    print("  https://redirect.url?request_token=XXXXXXXXXXX&state=12345")
    print("Copy the request_token value from that URL.\n")

    # Step 2: Get request token from user
    request_token = input("Paste request_token here: ").strip()

    if not request_token:
        print("ERROR: No request token provided. Exiting.")
        return

    print("\n[STEP 3] Generating access token...")

    try:
        # Generate session without version ID
        session = login.generate_session_without_versionId(request_token, SECRET_KEY)
        access_token = login.get_access_token(API_KEY, session, STATE)

        if access_token:
            print(f"\n✅ ACCESS TOKEN GENERATED SUCCESSFULLY!")
            print(f"Token: {access_token[:30]}...")

            # Save to file
            with open("access_token.txt", "w") as f:
                f.write(access_token)
            print("\n✅ Saved to access_token.txt")
            print("\nYou can now run the terminal:")
            print("  streamlit run sharekhan_terminal.py")
        else:
            print("\n❌ Failed to generate access token. Please try again.")

    except Exception as e:
        print(f"\n❌ Error: {e}")
        print("\nCommon fixes:")
        print("  - Make sure API_KEY and SECRET_KEY are correct")
        print("  - Make sure request_token is fresh (one-time use)")
        print("  - Check your internet connection")


if __name__ == "__main__":
    main()
