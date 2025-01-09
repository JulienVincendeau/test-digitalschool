import datetime
from pathlib import Path
from google.cloud import bigquery

# Configuration
client = bigquery.Client(project="sbx-mydigitalschool-2025")
TABLE_ID = 'sbx-mydigitalschool-2025.test_grun.usa_1910_2013'
OUTPUT_DIR = Path("/tmp")
OUTPUT_FILE = OUTPUT_DIR / "scr.txt"

def query_data():
    """Execute la requête sur BigQuery et retourne les résultats."""
    query = """
        SELECT gender, name, number, state, year
        FROM `bigquery-public-data.usa_names.usa_1910_2013`
        WHERE state = "TX"
        LIMIT 100
    """
    query_job = client.query(query)  # API request
    return query_job.result()  # Attend la fin de la requête

def insert_data(rows):
    """Insère des lignes dans BigQuery par lot."""
    rows_to_insert = [
        {
            'gender': row.gender,
            'name': row.name,
            'number': row.number,
            'state': row.state,
            'year': row.year
        }
        for row in rows
    ]

    # Insertion en lot
    errors = client.insert_rows_json(TABLE_ID, rows_to_insert)
    if not errors:
        print("All rows successfully inserted.")
    else:
        print(f"Errors encountered during insertion
