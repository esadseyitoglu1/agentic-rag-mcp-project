import os
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.environ["TRELLO_API_KEY"]
TOKEN = os.environ["TRELLO_TOKEN"]

r = requests.get(
    "https://api.trello.com/1/members/me/boards",
    params={"key": API_KEY, "token": TOKEN, "fields": "name,id"}
)
print(f"Status: {r.status_code}")
print(f"Yanit: {r.text[:500]}")

if r.status_code != 200:
    print("HATA: Token gecersiz veya yetkilendirilmemis olabilir.")
else:
    boards = r.json()
    for b in boards:
        print(f"Board: {b['name']} | ID: {b['id']}")
        lists_r = requests.get(
            f"https://api.trello.com/1/boards/{b['id']}/lists",
            params={"key": API_KEY, "token": TOKEN}
        )
        for lst in lists_r.json():
            print(f"  Liste: {lst['name']} | ID: {lst['id']}")
