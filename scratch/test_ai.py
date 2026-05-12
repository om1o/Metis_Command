import json
import requests
import sys
import os
sys.path.insert(0, os.path.abspath("."))
import auth_local

API_URL = "http://127.0.0.1:7331"

def ask_metis(prompt: str, role: str = "manager") -> str:
    print(f"\n--- [TEST {role}] {prompt} ---")
    req = {
        "session_id": "test_session",
        "message": prompt,
        "role": role
    }
    response_text = ""
    try:
        headers = auth_local.bearer_header()
        r = requests.post(f"{API_URL}/chat", json=req, stream=True, timeout=120, headers=headers)
        r.raise_for_status()
        for line in r.iter_lines():
            if line:
                decoded = line.decode("utf-8")
                if decoded.startswith("data: "):
                    data_str = decoded[6:]
                    if data_str == "{}":
                        continue
                    try:
                        data = json.loads(data_str)
                        if data.get("type") == "token":
                            print(data.get("delta", ""), end="", flush=True)
                            response_text += data.get("delta", "")
                        elif data.get("type") == "done":
                            print(f"\n[DONE in {data.get('duration_ms')}ms]")
                    except json.JSONDecodeError:
                        pass
        return response_text
    except Exception as e:
        print(f"\n[ERROR] {e}")
        return ""

if __name__ == "__main__":
    tests = [
        ("EASY", "What is 2+2? Reply in exactly one sentence.", "manager"),
        ("MEDIUM", "Write a Python function to calculate the 10th Fibonacci number and return it.", "coder"),
        ("HARD", "Find out the current price of Bitcoin. If you don't know, explain how you would find it using your tools.", "researcher"),
        ("INSANELY HARD", "Read the 'metis.spec' file in this directory and summarize how the executable is built.", "scholar")
    ]
    
    for difficulty, prompt, role in tests:
        print(f"\n========== {difficulty} ==========")
        ask_metis(prompt, role=role)

