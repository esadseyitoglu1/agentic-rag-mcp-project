import os
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.environ.get("TRELLO_API_KEY")
TOKEN = os.environ.get("TRELLO_TOKEN")
BOARD_ID = "6a589316d28190538a5e6959"

# Mevcut listeleri al
r = requests.get(
    f"https://api.trello.com/1/boards/{BOARD_ID}/lists",
    params={"key": API_KEY, "token": TOKEN}
)
existing_lists = {lst["name"].upper(): lst["id"] for lst in r.json()}

target_lists = ["KRITIK BUGLAR", "ORTA BUGLAR", "DÜŞÜK BUGLAR"]

for t_list in target_lists:
    if t_list not in existing_lists:
        # Listeyi oluştur
        print(f"Olusturuluyor: {t_list}")
        create_r = requests.post(
            "https://api.trello.com/1/lists",
            params={"name": t_list, "idBoard": BOARD_ID, "key": API_KEY, "token": TOKEN}
        )
        if create_r.status_code == 200:
            existing_lists[t_list] = create_r.json()["id"]
        else:
            print(f"Hata {t_list}: {create_r.text}")

print("TUM LISTELER:")
for name, lid in existing_lists.items():
    print(f"{name}: {lid}")
