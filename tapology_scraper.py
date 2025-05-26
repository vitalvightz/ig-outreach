import os
import json
import time
import random
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from playwright.sync_api import sync_playwright

# Authenticate with Google Sheets
def connect_to_sheet():
    creds_json = os.environ["GOOGLE_APPLICATION_CREDENTIALS"]
    with open("creds.json", "w") as f:
        f.write(creds_json)

    scope = ['https://spreadsheets.google.com/feeds',
             'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_name("creds.json", scope)
    client = gspread.authorize(creds)
    sheet = client.open("IG LEAD SCRAPER - TAPOLOGY").worksheet("IG LEAD SCRAPER - TAPOLOGY")
    return sheet

# Extract event URLs from the promotion page
def get_event_links(page, limit=5):
    page.goto("https://www.tapology.com/fightcenter/promotions/55-cage-warriors-fighting-championship-cwfc")
    page.wait_for_timeout(3000)
    return [a.get_attribute("href") for a in page.query_selector_all(".fightCard a.name")][:limit]

# Scrape fighters from an event page
def scrape_event_data(page, url):
    page.goto(url)
    time.sleep(random.uniform(2, 4))
    event_name = page.query_selector("h1")
    fight_blocks = page.query_selector_all(".fightCard")
    fighters_data = []

    for fight in fight_blocks:
        try:
            fighter_tags = fight.query_selector_all(".fightCardFighterBout a")
            if len(fighter_tags) != 2:
                continue
            fighter_1 = fighter_tags[0].inner_text().strip()
            fighter_2 = fighter_tags[1].inner_text().strip()
            record_tag = fight.query_selector(".record")
            record = record_tag.inner_text().strip() if record_tag else "N/A"
            fight_date = page.query_selector(".details .info .date")
            fight_date = fight_date.inner_text().strip() if fight_date else "N/A"

            fighters_data.append([
                fighter_1,
                record,
                fight_date,
                fighter_2,
                "",
                "",
                "",
                event_name.inner_text().strip() if event_name else "",
                url
            ])
        except:
            continue

    return fighters_data

# Main function to run scraper and upload to Google Sheets
def run_scraper():
    sheet = connect_to_sheet()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        base_url = "https://www.tapology.com"
        event_paths = get_event_links(page, limit=5)
        all_fighter_data = []

        for path in event_paths:
            if path:
                url = base_url + path
                all_fighter_data.extend(scrape_event_data(page, url))

        if all_fighter_data:
            sheet.append_rows(all_fighter_data, value_input_option="USER_ENTERED")
            print(f"Scraped and saved {len(all_fighter_data)} fighter entries.")
        else:
            print("No data found.")

        browser.close()

if __name__ == "__main__":
    run_scraper()