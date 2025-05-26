import os
import time
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

# === SETTINGS ===
SHEET_NAME = "IG LEAD SCRAPER - TAPOLOGY"
TAB_NAME = "IG LEAD SCRAPER - TAPOLOGY"
MAX_EVENTS_PER_PROMOTION = 5

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

# === SETUP SHEETS ===
def connect_to_sheet():
    creds_json = os.environ["GOOGLE_APPLICATION_CREDENTIALS"]
    with open("creds.json", "w") as f:
        f.write(creds_json)
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name("creds.json", scope)
    client = gspread.authorize(creds)
    return client.open(SHEET_NAME).worksheet(TAB_NAME)

# === SCRAPER ===
def scrape_fighters():
    sheet = connect_to_sheet()
    print("Connected to Google Sheet.")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        all_rows = []

        for promo_url in PROMOTION_URLS:
            print(f"Fetching: {promo_url}")
            page.goto(promo_url)
            time.sleep(2)
            html = page.content()
            soup = BeautifulSoup(html, "html.parser")
            event_links = soup.select(".event a.name")[:MAX_EVENTS_PER_PROMOTION]

            for link in event_links:
                event_url = "https://www.tapology.com" + link.get("href")
                page.goto(event_url)
                time.sleep(2)
                event_html = page.content()
                event_soup = BeautifulSoup(event_html, "html.parser")

                fights = event_soup.select(".fightCard")
                for fight in fights:
                    fighters = fight.select(".fighter a")
                    if len(fighters) >= 2:
                        for fighter in fighters:
                            name = fighter.text.strip()
                            fighter_url = "https://www.tapology.com" + fighter.get("href")
                            all_rows.append([name, fighter_url])

        print(f"Total fighters scraped: {len(all_rows)}")

        if all_rows:
            sheet.append_rows(all_rows)
            print("Data added to sheet.")
        else:
            print("No fighter data extracted.")

        browser.close()

if __name__ == "__main__":
    scrape_fighters()