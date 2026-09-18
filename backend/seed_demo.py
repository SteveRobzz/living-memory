"""Scripted demo state. Run if a live typing demo goes wrong.

    python seed_demo.py
"""
from datetime import datetime, timezone
import httpx

API = "http://localhost:8000"
JAN = "2026-01-05T09:00:00+00:00"
MAR = "2026-03-02T09:00:00+00:00"

def run():
    httpx.post(f"{API}/demo/reset", timeout=20)
    tok = httpx.post(f"{API}/auth/demo-login", json={"handle": "maya"}).json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    conv = httpx.post(f"{API}/conversations", json={"title": "Demo"}, headers=h).json()["id"]

    def clock(iso): httpx.post(f"{API}/demo/clock", json={"as_of": iso})
    def say(text):
        r = httpx.post(f"{API}/conversations/{conv}/messages",
                       json={"content": text}, headers=h, timeout=30).json()
        print(f"> {text}\n  {r['assistant_message']['content']}")

    clock(JAN)
    say("I'm building a game in Unity.")
    say("My favorite food is biryani.")
    clock(MAR)
    say("I switched my game to Godot.")

    tok2 = httpx.post(f"{API}/auth/demo-login", json={"handle": "dev"}).json()["token"]
    h2 = {"Authorization": f"Bearer {tok2}"}
    conv2 = httpx.post(f"{API}/conversations", json={"title": "Demo"}, headers=h2).json()["id"]
    httpx.post(f"{API}/conversations/{conv2}/messages",
               json={"content": "I'm building a game in Unreal."}, headers=h2, timeout=30)
    print("\nSeeded. Maya: Godot (Unity superseded). Dev: Unreal.")

if __name__ == "__main__":
    run()
