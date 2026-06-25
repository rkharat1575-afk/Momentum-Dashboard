"""
get_nifty_scripcodes.py
─────────────────────────────────────────────────────────────────
Downloads the NSE F&O scrip master from Sharekhan API and shows
you all available Nifty option scripcodes for use in WebSocket.

Run this AFTER daily_login.py to get current week's scripcodes.

Usage: python get_nifty_scripcodes.py
"""

from SharekhanApi.sharekhanConnect import SharekhanConnect
import pandas as pd
import os

API_KEY = "YOUR_API_KEY_HERE"   # Replace with your API Key


def main():
    # Load access token
    if not os.path.exists("access_token.txt"):
        print("ERROR: access_token.txt not found. Run daily_login.py first.")
        return

    with open("access_token.txt") as f:
        access_token = f.read().strip()

    print("Connecting to Sharekhan API...")
    sk = SharekhanConnect(API_KEY, access_token)

    print("Downloading NSE F&O Scrip Master (this may take a moment)...")
    try:
        data = sk.master("NF")
        df = pd.DataFrame(data)
        print(f"Total scrips downloaded: {len(df)}")
        print(f"Columns: {list(df.columns)}")
    except Exception as e:
        print(f"Error: {e}")
        return

    # Save full master
    df.to_csv("nf_scrip_master.csv", index=False)
    print("\nSaved full master to nf_scrip_master.csv")

    # Filter NIFTY options only
    # Adjust column names based on actual API response
    symbol_col = None
    for col in ["TradingSymbol", "tradingSymbol", "Symbol", "symbol", "ScripName", "scripname"]:
        if col in df.columns:
            symbol_col = col
            break

    if symbol_col:
        nifty_df = df[df[symbol_col].str.upper().str.startswith("NIFTY")]

        # Separate CE and PE
        nifty_ce = nifty_df[nifty_df[symbol_col].str.upper().str.endswith("CE")]
        nifty_pe = nifty_df[nifty_df[symbol_col].str.upper().str.endswith("PE")]

        print(f"\n📊 NIFTY Options Found:")
        print(f"  CE (Calls): {len(nifty_ce)}")
        print(f"  PE (Puts):  {len(nifty_pe)}")

        # Find scrip code column
        scrip_col = None
        for col in ["ScripCode", "scripCode", "Scripcode", "scripcode", "Token", "token"]:
            if col in df.columns:
                scrip_col = col
                break

        if scrip_col:
            print(f"\n🔑 Nifty CE Options (WebSocket token = 'NF' + ScripCode):")
            print("-" * 60)
            print(nifty_ce[[symbol_col, scrip_col]].to_string(index=False))

            print(f"\n🔑 Sample WebSocket tokens for CE:")
            for _, row in nifty_ce.head(5).iterrows():
                ws_token = f"NF{row[scrip_col]}"
                print(f"  {row[symbol_col]:<35} WS Token: {ws_token}")

        nifty_ce.to_csv("nifty_ce_scripcodes.csv", index=False)
        nifty_pe.to_csv("nifty_pe_scripcodes.csv", index=False)
        print("\n✅ Saved nifty_ce_scripcodes.csv and nifty_pe_scripcodes.csv")
        print("\nUse the 'WS Token' values in the terminal's WebSocket Token input box.")
    else:
        print("\nCould not find symbol column. Columns available:", list(df.columns))
        print("Check nf_scrip_master.csv and find the column containing option symbols.")


if __name__ == "__main__":
    main()
