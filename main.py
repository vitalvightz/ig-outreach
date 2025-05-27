# File: run_outreach.py
import openai
import gspread
import os
import json
import re
from oauth2client.service_account import ServiceAccountCredentials

def load_google_sheet():
    creds_json = os.environ["GOOGLE_APPLICATION_CREDENTIALS"]
    with open("creds.json", "w") as f:
        f.write(creds_json)

    scope = ['https://spreadsheets.google.com/feeds',
             'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_name("creds.json", scope)
    client_sheet = gspread.authorize(creds)
    sheet = client_sheet.open("IG DM AUTOMATION").sheet1
    return sheet, sheet.get_all_records()

def generate_prompt(name: str, notes: str) -> str:
    return (
        f"Write a grounded Instagram DM to {name}. Start with a short line based on this: '{notes}'. "
        f"Then, you must clearly include this line in flow: "
        f"'One of our fighters went 7-0 post-surgery after one tweak added 8% more power per strike.' "
        f"Make it sound natural and human, not robotic. Message should be 40–50 words."
    )

def review_message(message: str) -> str:
    review_prompt = f"""
You're reviewing an Instagram DM from a grounded performance director. 
Confirm:
- Tone is natural and calm
- 35–50 words
- No hype or hallucinated facts
- Must include: 7-0 post-surgery

Return ONLY:
ACCEPTED
or
REWRITE: <fixed message>

Here’s the message:
\"\"\"{message}\"\"\"
"""
    response = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"]).chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": review_prompt}],
        temperature=0,
        max_tokens=200
    )
    return response.choices[0].message.content.strip()

def ensure_7_0_presence(message: str) -> str:
    if "7-0" in message:
        return message
    insert_line = "One of our fighters went 7-0 post-surgery after one tweak added 8% more power per strike."
    if "tweak" in message or "power per strike" in message:
        return message.replace("after", f"{insert_line} After", 1)
    return f"{message.strip()} {insert_line}"

def run_outreach():
    sheet, data = load_google_sheet()
    print(f"Rows pulled: {len(data)}")

    client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    for i, row in enumerate(data):
        if not row.get("Message"):
            name = row.get("Name", "fighter")
            notes = row.get("Notes", "").strip()
            prompt = generate_prompt(name, notes)

            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=150
            )
            message = response.choices[0].message.content.strip()
            review = review_message(message)

            if review.startswith("REWRITE:"):
                final_message = review.replace("REWRITE:", "").strip()
            elif review == "ACCEPTED":
                final_message = message
            else:
                final_message = "REVIEW FAILED"

            final_message = ensure_7_0_presence(final_message)

            if final_message != "REVIEW FAILED":
                sheet.update_cell(i + 2, 4, final_message)
                print(f"Updated row {i + 2}: {final_message}")
            else:
                print(f"Skipped row {i + 2}: Review failed")

    print("All messages processed.")