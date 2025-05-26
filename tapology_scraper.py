import requests
from bs4 import BeautifulSoup
import re
import gspread
import os
import json
from datetime import datetime
from oauth2client.service_account import ServiceAccountCredentials

# Google Sheets setup
creds_json = os.environ["GOOGLE_APPLICATION_CREDENTIALS"]
with open("creds.json", "w") as f:
    f.write(creds_json)

scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
creds = ServiceAccountCredentials.from_json_keyfile_name("creds.json", scope)
client = gspread.authorize(creds)
sheet = client.open("IG LEAD SCRAPER – TAPOLOGY").sheet1

# Promotions and URLs
promotions = {
    "Cage Warriors": "https://www.tapology.com/fightcenter/promotions/55-cage-warriors-fighting-championship-cwfc",
    "Polaris": "https://www.tapology.com/fightcenter/promotions/2673-polaris-ppjji",
    "Oktagon MMA": "https://www.tapology.com/fightcenter/promotions/1964-okatgon-mma-okmma",
    "Glory Kickboxing": "https://www.tapology.com/fightcenter/promotions/2605-glory-kickboxing-gk",
    "Matchroom Boxing": "https://www.tapology.com/fightcenter/promotions/2484-matchroom-boxing-mb",
    "Boxxer": "https://www.tapology.com/fightcenter/promotions/3272-ultimate-boxxer-ub",
    "LFA": "https://www.tapology.com/fightcenter/promotions/1815-legacy-fighting-alliance-lfa",
    "BRAVE CF": "https://www.tapology.com/fightcenter/promotions/1782-brave-combat-federation-bcf",
    "Golden Boy Promotions": "https://www.tapology.com/fightcenter/promotions/1979-golden-boy-promotions-gbp"
}

# Clear existing sheet content
sheet.resize(1)
sheet.append_row(["Name", "Record", "Fight Date", "Opponent", "Result", "Method", "Weight Class", "Event Name", "Tapology URL"])

def extract_fighter_data(event_url):
    fight_resp = requests.get(event_url)
    fight_soup = BeautifulSoup(fight_resp.text, "html.parser")
    event_name = fight_soup.find("h1").text.strip()

    rows = fight_soup.select("table.fightCard tr")
    for row in rows:
        cols = row.find_all("td")
        if len(cols) < 6:
            continue

        try:
            name = cols[1].select_one(".fighterLink").text.strip()
            record = cols[1].select_one(".record").text.strip("() ")
            opponent = cols[3].select_one(".fighterLink").text.strip()
            result = cols[0].text.strip()
            method = cols[4].text.strip()
            weight_class = cols[5].text.strip()
            date_text = fight_soup.select_one(".right .alt span").text.strip()
            fight_date = datetime.strptime(date_text, "%b %d, %Y").strftime("%Y-%m-%d")

            sheet.append_row([
                name, record, fight_date, opponent, result, method, weight_class, event_name, event_url
            ])
        except:
            continue

def process_promotion(name, base_url):
    res = requests.get(base_url)
    soup = BeautifulSoup(res.text, "html.parser")
    links = soup.select(".event a.name")[:3]  # Adjust this to control how many events are pulled

    for link in links:
        href = link.get("href")
        event_url = f"https://www.tapology.com{href}"
        extract_fighter_data(event_url)

for name, url in promotions.items():
    process_promotion(name, url)

print("Scraping complete.")
