import openai
import gspread
import os
import json
from oauth2client.service_account import ServiceAccountCredentials

def run_outreach():
    # Write Google credentials from environment to a file
    creds_json = os.environ["GOOGLE_APPLICATION_CREDENTIALS"]
    with open("creds.json", "w") as f:
        f.write(creds_json)

    # Authenticate with Google Sheets
    scope = ['https://spreadsheets.google.com/feeds',
             'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_name("creds.json", scope)
    client_sheet = gspread.authorize(creds)

    # Load sheet
    sheet = client_sheet.open("IG DM AUTOMATION").sheet1
    data = sheet.get_all_records()
    print(f"Rows pulled: {len(data)}")

    # Initialize OpenAI client
    client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    # Fixed offer message
    core_message = "One of our fighters went 7-0 post-surgery after one tweak added 8% more power per strike. Want me to send over how?"

    for i, row in enumerate(data):
        if not row.get("Message"):
            name = row.get("Name", "fighter")
            notes = row.get("Notes", "").strip()

            base_prompt = (
                f"You're a calm, sharp performance director writing an Instagram DM to a fighter named {name}. "
                f"The following note is background about *them*, not you, and should be used for a natural opening: '{notes}'. "
                f"Then, transition into this line: '{core_message}'. "
                f"Keep it 40–55 words. No emojis. Never say 'I heard'. Never misattribute pronouns. "
                f"Tone must be confident, grounded, and personal — never hypey or generic."
            )

            # First draft
            draft_response = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": base_prompt}],
                temperature=0.7,
                max_tokens=100
            )
            message = draft_response.choices[0].message.content.strip()

            # Self-review
            review_prompt = (
                f"Review the following message for clarity, tone, and logical correctness:\n\n'{message}'\n\n"
                f"Does it avoid hallucination, incorrect pronouns, overhype, or irrelevant content? "
                f"If yes, return 'ACCEPTED'. If not, rewrite it based on the original intent, tone, and constraint (40–55 words)."
            )

            review_response = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": review_prompt}],
                temperature=0.4,
                max_tokens=100
            )
            final_output = review_response.choices[0].message.content.strip()

            final_message = message if final_output == "ACCEPTED" else final_output

            print(f"Updating row {i + 2} with message: {final_message}")
            sheet.update_cell(i + 2, 4, final_message)

    print("All messages updated.")

run_outreach()