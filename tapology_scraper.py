# tapology_scraper.py

import os
import asyncio
import json
import gspread
from playwright.async_api import async_playwright
from oauth2client.service_account import ServiceAccountCredentials

# Google Sheets Setup
def setup_google_sheet():
    creds_json = os.environ["GOOGLE_APPLICATION_CREDENTIALS"]
    with open("gcreds.json", "w") as f:
        f.write(creds_json)

    scope = ['https://spreadsheets.google.com/feeds',
             'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_name("gcreds.json", scope)
    client = gspread.authorize(creds)
    sheet = client.open("IG LEAD SCRAPER - TAPOLOGY").worksheet("IG LEAD SCRAPER - TAPOLOGY")
    return sheet

# Scraper function
async def scrape_events():
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

    sheet = setup_google_sheet()
    print("Connected to Google Sheet.")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        for promo_url in PROMOTION_URLS:
            print(f"Fetching: {promo_url}")
            await page.goto(promo_url)
            await page.wait_for_timeout(3000)
            if await page.is_visible("button:has-text(\"Accept\")"):
                await page.click("button:has-text(\"Accept\")")

            events = await page.query_selector_all(".fcListing a.name")
            event_links = [await e.get_attribute("href") for e in events if e]
            event_links = list(filter(None, event_links))[:5]  # Limit to 5 events

            for event_link in event_links:
                event_url = f"https://www.tapology.com{event_link}"
                await page.goto(event_url)
                await page.wait_for_timeout(3000)
                print(f"Visiting event: {event_url}")

                fighter_elems = await page.query_selector_all("a.fightCardFighterBoutLink")
                for elem in fighter_elems:
                    name = (await elem.inner_text()).strip()
                    href = await elem.get_attribute("href")
                    full_url = f"https://www.tapology.com{href}" if href else ""

                    if name and href:
                        sheet.append_row([name, full_url])
                        print(f"Added: {name} - {full_url}")

        await browser.close()

    print("Done scraping.")

if __name__ == "__main__":
    asyncio.run(scrape_events())