import requests
from bs4 import BeautifulSoup
import gspread
import os
import json
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import time

# URLs to scrape
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

# Connect to Google Sheet
def connect_to_sheet():
    creds_json = os.environ["GOOGLE_APPLICATION_CREDENTIALS"]
    with open("creds.json", "w") as f:
        f.write(creds_json)

    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_name("creds.json", scope)
    client = gspread.authorize(creds)
    sheet = client.open("IG LEAD SCRAPER - TAPOLOGY").worksheet("IG LEAD SCRAPER - TAPOLOGY")
    return sheet

# Get all event links from a promotion page
def get_event_links(promo_url):
    print(f"Fetching events from: {promo_url}")
    html = requests.get(promo_url).text
    soup = BeautifulSoup(html, 'html.parser')
    links = soup.select(".fightCard a.name")
    event_urls = ["https://www.tapology.com" + link['href'] for link in links]
    print(f"Found {len(event_urls)} events")
    return event_urls[:2]  # limit for debug

# Scrape fighters from a single event
def scrape_event(event_url):
    print(f"Scraping event: {event_url}")
    html = requests.get(event_url).text
    soup = BeautifulSoup(html, 'html.parser')

    event_name = soup.select_one(".content-title h1").text.strip()
    rows = soup.select("tr.fight")
    print(f"Found {len(rows)} fights")

    fight_data = []
    for row in rows:
        try:
            names = row.select(".fighter a")
            if len(names) != 2:
                continue

            date_str = soup.select_one(".details .add-details .left").text.strip()
            fight_date = datetime.strptime(date_str.split("\n")[0], "%b %d, %Y").strftime("%Y-%m-%d")

            fight_data.append({
                "Name": names[0].text.strip(),
                "Opponent": names[1].text.strip(),
                "Fight Date": fight_date,
                "Event Name": event_name,
                "Tapology URL": event_url
            })
        except Exception as e:
            print(f"Error parsing fight row: {e}")
    return fight_data

# Push to sheet
def push_to_sheet(sheet, fighter_rows):
    for row in fighter_rows:
        sheet.append_row([
            row.get("Name"),
            "",  # Record placeholder
            row.get("Fight Date"),
            row.get("Opponent"),
            "",  # Result placeholder
            "",  # Method placeholder
            "",  # Weight class placeholder
            row.get("Event Name"),
            row.get("Tapology URL")
        ])

# Full runner
def run_scraper():
    sheet = connect_to_sheet()
    all_fighters = []
    for url in PROMOTION_URLS:
        event_links = get_event_links(url)
        for link in event_links:
            fighters = scrape_event(link)
            all_fighters.extend(fighters)
            time.sleep(2)

    print(f"Total fighters scraped: {len(all_fighters)}")
    push_to_sheet(sheet, all_fighters)
    print("Done.")

if __name__ == "__main__":
    run_scraper()