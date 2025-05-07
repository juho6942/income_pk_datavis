import requests
import pandas as pd
from io import StringIO
import numpy as np
# URL for the table
url = "https://stat.hel.fi:443/api/v1/fi/Aluesarjat/tul/astul/alu_astul_006f.px"

# Example query - you'll need to adjust based on the actual metadata
def make_query(years):
    query = {
        "query": [
            {
            "code": "Vuosi",
            "selection": {
                "filter": "item",
                "values": years
            }
            },
            {
            "code": "Tiedot",
            "selection": {
                "filter": "item",
                "values": [
                "Median_svatv"
                ]
            }
            }
        ],
        "response": {
            "format": "csv"
        }
    }

    # Make the POST request
    response = requests.post(url, json=query)
    # Check if the request was successful
    if response.status_code == 200:
        #print(response.text)
        df = pd.read_csv(StringIO(response.text), sep=",")
        
        placeholder = [df.columns[i].split(' ')[0] for i in range(len(df.columns))]
        
        
        df.columns = placeholder
        df.replace('..',np.nan,inplace=True)
        df.dropna(how='all',inplace=True)

        df[years] = df[years].astype(float)
        print(df.head(), "\n")
    else:
        print(f"Error: {response.status_code}")
        print(response.text)
        df = pd.DataFrame()  # Return an empty DataFrame on error
    print('Done making query')
    return df
make_query(["2022","2021"])