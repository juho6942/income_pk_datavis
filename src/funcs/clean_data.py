import requests
import pandas as pd
from funcs.get_inc_data import make_query



def clean_data(df):
    """
    Clean the DataFrame by renaming columns and dropping unnecessary ones.
    """
    mask = df['Alue'].str.contains('piiri') == False
    df = df[mask]
    Aluecol = df['Alue'].str.split(' ', n=2, expand=True)
    mask2 = Aluecol[1].str.isnumeric()
    df = df[mask2]
    Aluecol=Aluecol[mask2]
    df['AlueNum'] = Aluecol[1]
    df['AlueNimi'] = Aluecol[2]
    df = df.drop(columns=['Alue'])
    df['KuntaNum'] = Aluecol[0]
    print('Done cleaning data')
    return df
