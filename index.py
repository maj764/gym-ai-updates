from flask import Flask, jsonify
import requests
from bs4 import BeautifulSoup
import google.generativeai as genai
import time
import mysql.connector
import re

app = Flask(__name__)

def fetch_and_analyze():
    # Configure Gemini
    genai.configure(api_key="AIzaSyB88tBlyPO0dopgu_ppMCPXkz5EFIv38FM")
    model = genai.GenerativeModel(model_name="gemini-2.0-flash")

    # Connect to MySQL
    db = mysql.connector.connect(
        host="localhost",
        user="root",
        password="",
        database="gym_ai_insights"
    )
    cursor = db.cursor()

    # PubMed scraping
    query_url = ('https://pubmed.ncbi.nlm.nih.gov/?term=(EMG+OR+hypertrophy+OR+"muscle+activation")+AND+'
                 '("resistance+training"+OR+bodybuilding+OR+strength)'
                 '&sort=date&size=100&datetype=pdat&mindate=2024/04/13&maxdate=2024/05/13')

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept-Language": "en-US,en;q=0.9"
    }

    def fetch_abstract(link):
        try:
            res = requests.get(link, headers=headers, timeout=10)
            soup = BeautifulSoup(res.text, "html.parser")
            abstract_tag = soup.find("div", class_="abstract-content")
            return abstract_tag.get_text(strip=True) if abstract_tag else "No abstract found"
        except Exception as e:
            print(f"Error fetching {link}: {e}")
            return "Error fetching abstract"

    articles = []
    for page in range(1, 3):
        res = requests.get(f"{query_url}&page={page}", headers=headers)
        soup = BeautifulSoup(res.text, "html.parser")
        blocks = soup.find_all("article", class_="full-docsum")
        for block in blocks:
            title_tag = block.find("a", class_="docsum-title")
            if not title_tag:
                continue
            title = title_tag.get_text(strip=True)
            link = "https://pubmed.ncbi.nlm.nih.gov" + title_tag["href"]
            abstract = fetch_abstract(link)

            cursor.execute(
                "INSERT INTO articles (title, abstract, pubmed_link) VALUES (%s, %s, %s)",
                (title, abstract, link)
            )
            article_id = cursor.lastrowid
            articles.append({"id": article_id, "title": title, "abstract": abstract, "link": link})
            db.commit()
            time.sleep(0.5)

    # AI prompt
    abstracts_text = "\n".join(
        f"{i+1}. {a['title']}\nAbstract: {a['abstract']}" for i, a in enumerate(articles)
    )

    prompt = (
        "You are analyzing recent research abstracts on resistance training and hypertrophy.\n"
        f"{abstracts_text}\n\n"
        "Please summarize key exercise changes under these *exact headings*:\n\n"
        "**Buffed Exercises**\n- [Exercise name]: [2-3 sentence explanation why it was found to be more effective]\n\n"
        "**Nerfed Exercises**\n- [Exercise name]: [2-3 sentence explanation why it was found to be less effective]\n\n"
        "Only return bullet points under those exact headings. Do not write any introduction or conclusion text."
    )

    response = model.generate_content(prompt)
    response_text = response.text

    buffed = re.search(r'\*\*Buffed Exercises\*\*(.*?)(\*\*Nerfed Exercises\*\*|$)', response_text, re.DOTALL | re.IGNORECASE)
    nerfed = re.search(r'\*\*Nerfed Exercises\*\*(.*)', response_text, re.DOTALL | re.IGNORECASE)

    buffed_lines = re.findall(r'-\s*(.+)', buffed.group(1).strip()) if buffed else []
    nerfed_lines = re.findall(r'-\s*(.+)', nerfed.group(1).strip()) if nerfed else []

    for line in buffed_lines:
        cursor.execute(
            "INSERT INTO ai_analyses (article_id, model_used, ai_prompt, ai_response, event) VALUES (%s, %s, %s, %s, %s)",
            (None, "gemini-2.0-flash", prompt, line, "buff")
        )
    for line in nerfed_lines:
        cursor.execute(
            "INSERT INTO ai_analyses (article_id, model_used, ai_prompt, ai_response, event) VALUES (%s, %s, %s, %s, %s)",
            (None, "gemini-2.0-flash", prompt, line, "nerf")
        )

    db.commit()
    cursor.close()
    db.close()
    return {"buffs": len(buffed_lines), "nerfs": len(nerfed_lines)}

@app.route("/run", methods=["GET"])
def run_analysis():
    result = fetch_and_analyze()
    return jsonify({"status": "completed", "inserted": result})

if __name__ == "__main__":
    app.run(debug=True)
