import requests
from bs4 import BeautifulSoup
import gspread
import os
import json
from datetime import datetime
from oauth2client.service_account import ServiceAccountCredentials

# Google Sheets setup
def connect_to_sheet():
    creds_json = os.environ["GOOGLE_APPLICATION_CREDENTIALS"]
    with open("creds.json", "w") as f:
        f.write(creds_json)

    scope = ['https://spreadsheets.google.com/feeds',
             'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_name("creds.json", scope)
    client = gspread.authorize(creds)
    return client.open("IG LEAD SCRAPER - TAPOLOGY").worksheet("IG LEAD SCRAPER - TAPOLOGY")

# List of Tapology event listing URLs for each promotion
PROMOTION_URLS = [
    "https://www.tapology.com/fightcenter/promotions/55-cage-warriors-fighting-championship-cwfc",
    "https://www.tapology.com/fightcenter/promotions/2673-polaris-ppjji",
    "https://www.tapology.com/fightcenter/promotions/1964-okatgon-mma-okmma",
    "https://www.tapology.com/fightcenter/promotions/2605-glory-kickboxing-gk",
    "https://www.tapology.com/fightcenter/promotions/2484-matchroom-boxing-mb",
    "https://www.tapology.com/fightcenter/promotions/3272-ultimate-boxxer-ub",
    "https://www.tapology.com/fightcenter/promotions/1815-legacy-fighting-alliance-lfa",
    "https://www.tapology.com/fightcenter/promotions/1782-brave-combat-federation-bcf",
    "https://www.tapology.com/fightcenter/promotions/1979-golden-boy-promotions-gbp"
]

# Extract fighter data from an event
def parse_fight_card(event_url):
    fighters = []
    try:
        res = requests.get(event_url)
        soup = BeautifulSoup(res.text, 'html.parser')
        bouts = soup.select(".fightCard .fight")
        for bout in bouts:
            try:
                names = bout.select(".fighter a span")
                name1 = names[0].text.strip() if len(names) > 0 else ""
                name2 = names[1].text.strip() if len(names) > 1 else ""

                records = bout.select(".record")
                record1 = records[0].text.strip() if len(records) > 0 else ""
                record2 = records[1].text.strip() if len(records) > 1 else ""

                result = bout.select_one(".result .outcome")
                method = bout.select_one(".method")
                weight = bout.select_one(".weight-class")

                result_text = result.text.strip() if result else ""
                method_text = method.text.strip() if method else ""
                weight_class = weight.text.strip() if weight else ""

                fight_date_tag = soup.select_one(".event-date")
                fight_date = fight_date_tag.text.strip() if fight_date_tag else ""

                event_name_tag = soup.select_one("h1.pageTitle")
                event_name = event_name_tag.text.strip() if event_name_tag else ""

                fighters.append([name1, record1, fight_date, name2, result_text, method_text, weight_class, event_name, event_url])
                fighters.append([name2, record2, fight_date, name1, result_text, method_text, weight_class, event_name, event_url])
            except Exception as e:
                continue
    except:
        pass
    return fighters

# Scrape all event pages for one promotion
def scrape_promotion_events(promo_url):
    res = requests.get(promo_url)
    soup = BeautifulSoup(res.text, 'html.parser')
    events = soup.select(".event a.name")
    event_urls = ["https://www.tapology.com" + a['href'] for a in events if a['href']]
    all_fighters = []
    for url in event_urls:
        all_fighters.extend(parse_fight_card(url))
    return all_fighters

# Remove duplicate entries
seen = set()
def dedupe(rows):
    unique = []
    for row in rows:
        key = tuple(row[:4])
        if key not in seen:
            seen.add(key)
            unique.append(row)
    return unique

# Main scraping flow
def run_scraper():
    sheet = connect_to_sheet()
    all_data = []
    for promo_url in PROMOTION_URLS:
        all_data.extend(scrape_promotion_events(promo_url))

    clean_data = dedupe(all_data)
    sheet.clear()
    sheet.append_row(["Name", "Record", "Fight Date", "Opponent", "Result", "Method", "Weight Class", "Event Name", "Tapology URL"])
    sheet.append_rows(clean_data)
    print(f"Scraped and saved {len(clean_data)} fighter entries.")

run_scraper()
