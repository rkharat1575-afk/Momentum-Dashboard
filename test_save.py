# test_save.py - tests if we can write files
import json, os

print(f"Current folder: {os.getcwd()}")

# Write test
with open("live_ticks.json", "w") as f:
    json.dump({"test": "working"}, f)

print("✅ File write works!")
print(f"File size: {os.path.getsize('live_ticks.json')} bytes")
