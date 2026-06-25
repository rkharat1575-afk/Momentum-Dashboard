import json

with open('C:\\sharekhan_terminal\\scrip_master.json', 'r') as f:
    data = json.load(f)

print("Matches for 23200 CE:")
for v in data:
    if '23200' in str(v) and v.get('optionType') == 'CE':
        print(f"Token: {v.get('scripCode')} | Expiry: {v.get('expiry')} | Strike: {v.get('strikePrice')}")
