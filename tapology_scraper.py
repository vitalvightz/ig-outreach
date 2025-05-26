import os
import time
import gspread
from oauth2client.service_account import ServiceAccountCredentials
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

def connect_to_sheet():
    creds_json = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not creds_json:
        raise ValueError("Missing GOOGLE_APPLICATION_CREDENTIALS env var.")
    with open("creds.json", "w") as f:
        f.write(creds_json)
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name("creds.json", scope)
    client = gspread.authorize(creds)
    return client.open(SHEET_NAME).worksheet(TAB_NAME)

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
            page.wait_for_selector(".event a.name", timeout=5000)
            event_links = page.query_selector_all(".event a.name")[:MAX_EVENTS_PER_PROMOTION]

            for link in event_links:
                href = link.get_attribute("href")
                if not href:
                    continue
                event_url = "https://www.tapology.com" + href
                page.goto(event_url)
                time.sleep(2)
                event_name = page.query_selector("h1").inner_text().strip()
                try:
                    page.wait_for_selector(".fightCard", timeout=5000)
                    fights = page.query_selector_all(".fightCard")

                    for fight in fights:
                        weight_el = fight.query_selector(".details .weight")
                        weight_class = weight_el.inner_text().strip() if weight_el else ""

                        date_el = page.query_selector(".date")
                        fight_date = date_el.inner_text().strip() if date_el else ""

                        fighter_links = fight.query_selector_all(".fighter a")
                        if not fighter_links:
                            continue

                        for f_link in fighter_links:
                            f_name = f_link.inner_text().strip()
                            f_href = f_link.get_attribute("href")
                            f_url = "https://www.tapology.com" + f_href

                            # Open fighter profile in new tab
                            fighter_page = browser.new_page()
                            fighter_page.goto(f_url)
                            time.sleep(2)

                            try:
                                fighter_page.wait_for_selector(".record", timeout=5000)
                                record = fighter_page.query_selector(".record").inner_text().strip()

                                # Grab most recent fight row
                                recent_fight_row = fighter_page.query_selector("table.fights tr:nth-of-type(2)")
                                if recent_fight_row:
                                    tds = recent_fight_row.query_selector_all("td")
                                    result = tds[0].inner_text().strip()
                                    opponent = tds[2].inner_text().strip()
                                    method = tds[3].inner_text().strip()
                                else:
                                    result = opponent = method = ""

                            except:
                                record = result = opponent = method = ""

                            fighter_page.close()

                            all_rows.append([
                                f_name, record, fight_date, opponent,
                                result, method, weight_class, event_name, f_url
                            ])

                except:
                    print(f"Could not load fights on {event_url}")
                    continue

        print(f"Total fighters scraped: {len(all_rows)}")

        if all_rows:
            sheet.append_rows(all_rows, value_input_option="RAW")
            print("Data added to sheet.")
        else:
            print("No fighter data extracted.")

        browser.close()

if __name__ == "__main__":
    scrape_fighters()