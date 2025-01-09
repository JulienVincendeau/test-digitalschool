from google.cloud import bigquery

client = bigquery.Client(project="sbx-mydigitalschool-2025")
TABLE_ID = 'sbx-mydigitalschool-2025.test_grun.usa_1910_2013'

def main():

    QUERY = (f'TRUNCATE TABLE {TABLE_ID}  ')
    query_job = client.query(QUERY)  # API request
    rows = query_job.result()  # Waits for query to finish

    # Perform a query.
    QUERY = (
        'SELECT   `gender`,`name`,`number`,`state`,`year` '
        ' FROM `bigquery-public-data.usa_names.usa_1910_2013` '
        'WHERE state = "TX" '
        'LIMIT 100')
    query_job = client.query(QUERY)  # API request
    rows = query_job.result()  # Waits for query to finish

    rows_to_insert=[]
    for row in rows: 
        errors = client.insert_rows_json(TABLE_ID, [{
            'gender' : row.gender,
            'name' : row.name,
            'number' : row.number,
            'state' : row.state,
            'year' : row.year
        }] )
        if errors == [] :
            print("News rows added")
        else:
            print(f"!!Row {row.name} {row.state} on Error : {errors}")

main()