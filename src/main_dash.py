import dash
from dash import dcc, html, Input, Output, Patch, State
import pandas as pd
import geopandas as gpd
import plotly.express as px
import json
import requests
from shapely.geometry import shape
import warnings
from functools import lru_cache
import os
from funcs.get_inc_data import make_query
from funcs.clean_data import clean_data


# --- Configuration ---
WFS_BASE_URL = "https://kartta.hel.fi/ws/geoserver/avoindata/wfs"
LAYER_NAME = "avoindata:Seutukartta_aluejako_pienalue"
OUTPUT_FORMAT = "application/json"
SOURCE_CRS = "EPSG:3879"
TARGET_CRS = "EPSG:4326"
MUNICIPALITY_CODES = {'091': 'Helsinki', '049': 'Espoo', '092': 'Vantaa'}
LOCATION_ID_COL = 'nimi'
ASSETS_FOLDER = "assets"
GEOJSON_FILENAME = "helsinki_regions.json"
AVAILABLE_YEARS = list(range(2005, 2024))
DEFAULT_YEAR = max(AVAILABLE_YEARS)
MIN_YEAR = min(AVAILABLE_YEARS)
MAX_YEAR = max(AVAILABLE_YEARS)

# --- Process & Cache Geospatial Data at Startup ---
def download_and_optimize_geojson():
    """Download, optimize, and save GeoJSON for future use"""
    # Create assets directory if it doesn't exist
    if not os.path.exists(ASSETS_FOLDER):
        os.makedirs(ASSETS_FOLDER)
    
    # Full path to the GeoJSON file
    geojson_path = os.path.join(ASSETS_FOLDER, GEOJSON_FILENAME)
    
    # Check if we already have the file
    if os.path.exists(geojson_path):
        print(f"Using cached GeoJSON from {geojson_path}")
        return geojson_path
    
    print("Downloading and optimizing GeoJSON data...")
    params = {
        'service': 'WFS', 
        'version': '2.0.0', 
        'request': 'GetFeature',
        'typeNames': LAYER_NAME, 
        'outputFormat': OUTPUT_FORMAT, 
        'srsName': SOURCE_CRS
    }
    
    try:
        # Download the data
        response = requests.get(WFS_BASE_URL, params=params)
        response.raise_for_status()
        geojson_data = response.json()
        
        # Process GeoJSON - filter municipalities and optimize
        features = geojson_data['features']
        
        # Filter features by municipality code
        filtered_features = []
        for feature in features:
            if feature['properties'].get('kunta') in MUNICIPALITY_CODES.keys():
                filtered_features.append(feature)
        
        geojson_data['features'] = filtered_features
        
        # Convert to GeoDataFrame for processing
        properties = [feature['properties'] for feature in filtered_features]
        geometries = [shape(feature['geometry']) for feature in filtered_features]
        gdf = gpd.GeoDataFrame(properties, geometry=geometries, crs=SOURCE_CRS)
        
        # Reproject to target CRS
        gdf = gdf.to_crs(TARGET_CRS)
        
        # Simplify geometries for better performance
        gdf['geometry'] = gdf['geometry'].simplify(tolerance=0.00001, preserve_topology=True)
        
        # Convert back to GeoJSON but with reduced precision
        optimized_geojson = json.loads(gdf.to_json())
        
        # Reduce precision of coordinates to 5 decimal places
        for feature in optimized_geojson['features']:
            if feature['geometry']['type'] == 'Polygon':
                for ring in feature['geometry']['coordinates']:
                    for coord in ring:
                        coord[0] = round(coord[0], 6)
                        coord[1] = round(coord[1], 6)
            elif feature['geometry']['type'] == 'MultiPolygon':
                for polygon in feature['geometry']['coordinates']:
                    for ring in polygon:
                        for coord in ring:
                            coord[0] = round(coord[0], 6)
                            coord[1] = round(coord[1], 6)
        
        # Remove unnecessary properties to reduce file size
        for feature in optimized_geojson['features']:
            # Keep only essential properties
            essential_props = {'nimi', 'kunta'}
            feature['properties'] = {k: v for k, v in feature['properties'].items() if k in essential_props}
        
        # Save optimized GeoJSON
        with open(geojson_path, 'w') as f:
            json.dump(optimized_geojson, f)
        
        print(f"Optimized GeoJSON saved to {geojson_path}")
        return geojson_path
    
    except Exception as e:
        print(f"Error processing GeoJSON: {str(e)}")
        return None

# --- Load Income Data ---
@lru_cache(maxsize=1)
def get_income_data():
    """Load income data with caching"""
    from funcs.get_inc_data import make_query
    from funcs.clean_data import clean_data
    
    try:
        inc_data = make_query(list(map(str,AVAILABLE_YEARS)))
        
        return clean_data(inc_data)
    except Exception as e:
        print(f"Error loading income data: {str(e)}")
        return None

def prepare_data():
    """Prepare data for the map - called once at startup"""
    # Get income data
    income_data = get_income_data()
    if income_data is None:
        return None
    
    # Prepare a dataframe with just the regions and their income values
    print(income_data.columns)
    income_cols = list(map(str,AVAILABLE_YEARS))
    income_cols.append('AlueNimi')
    return income_data[income_cols].copy()

# --- Initialize App Components ---
# Download and optimize GeoJSON at startup
geojson_path = download_and_optimize_geojson()

# Prepare income data
income_df = prepare_data()

# Initialize the Dash app
app = dash.Dash(__name__, title="Helsinki Region Income Map")
server = app.server  # For deployment

# App Layout
app.layout = html.Div([
    html.H1("Helsinki Region Income Map",style={'textAlign': 'center'}),
    html.P("Displays Median household income of taxpayers by region for Helsinki, Espoo, and Vantaa.",style={'textAlign': 'center'}),
    
    html.Div([
        html.Button('Play', id='play-button',n_clicks=0),
        dcc.Slider(MIN_YEAR,MAX_YEAR,1,value=MAX_YEAR,id='year-selector',marks={i:str(i) for i in AVAILABLE_YEARS}),
        dcc.Interval(
            id='interval-component',
            interval=1200,  # Change to 1000ms (1 second)
            n_intervals=0,
            disabled=True  # Start as disabled
        )
    ],style={'textAlign': 'center'}),
    # Loading indicator
    dcc.Loading(
        id="loading-map",
        type="default",
        children=[
            # The map
            dcc.Graph(
                id='income-map',
                style={'height': '700px'},
                config={'scrollZoom': True},
                # Initialize the figure with a blank basemap to avoid loading delays
                figure={
                    'data': [],
                    'layout': {
                        'mapbox': {
                            'style': "carto-positron",
                            'center': {'lon': 24.9384, 'lat': 60.1699},  # Helsinki coordinates
                            'zoom': 9
                        },
                        'margin': {"r":0,"t":0,"l":0,"b":0},
                        'height': 700
                    }
                }
            )
        ]
    ),
    
    # Data explorer section
    html.Div([
        html.H3("Data Explorer"),
        html.Button('Show Data Table', id='show-data-button', n_clicks=0),
        html.Div(id='data-table-container'),
        
        html.Button('Show Memory Usage', id='show-memory-button', n_clicks=0),
        html.Div(id='memory-usage-container'),
    ], style={'marginTop': '20px'})
])

PLAY_INTERVAL_MS = 1000  # Change from 800ms to 1000ms (1 second)

# In the toggle_interval callback, change 'Pause' to 'Stop'
@app.callback(
    [Output('interval-component', 'disabled'),
     Output('play-button', 'children'),
     Output('year-selector', 'value')], 
    [Input('play-button', 'n_clicks')],
    [State('interval-component', 'disabled'),
     State('year-selector', 'value')] 
)
def toggle_interval(n_clicks, is_disabled, current_year):
    if n_clicks == 0:
        # Initial load, keep interval disabled
        return True, 'Play', dash.no_update

    if is_disabled:
        # If disabled, enable it and change button to 'Stop'
        # If slider is already at max, reset to min before playing
        new_year = MIN_YEAR if current_year == MAX_YEAR else dash.no_update
        return False, 'Stop', new_year  # Changed 'Pause' to 'Stop'
    else:
        # If enabled, disable it and change button to 'Play'
        return True, 'Play', dash.no_update

# Also in the update_slider_value callback, change 'Play' to 'Play'
@app.callback(
    [Output('year-selector', 'value', allow_duplicate=True),
     Output('interval-component', 'disabled', allow_duplicate=True),
     Output('play-button', 'children', allow_duplicate=True)],
    [Input('interval-component', 'n_intervals')],
    [State('year-selector', 'value')],
    prevent_initial_call=True
)
def update_slider_value(n_intervals, current_year):
    if current_year < MAX_YEAR:
        next_year = current_year + 1
        return next_year, dash.no_update, dash.no_update
    else:
        # Reached the end, stop the interval and reset button
        return MAX_YEAR, True, 'Play' 
# Callback for initial map creation (server-side)
@app.callback(
    Output('income-map', 'figure'),
    Input('income-map', 'id'),  # Dummy input to trigger on load
    Input('year-selector','value')
)
def create_map(_, slider):
    if geojson_path is None or income_df is None:
        return px.scatter(title="Error loading data")
    disp_year = slider 
    # Use the path to the static asset file instead of loading the entire GeoJSON
    geojson_asset_path = "/" + geojson_path  # Important: use the web path, not the system path
    
    try:
        fig = px.choropleth_mapbox(
            income_df,  # Your DataFrame with region names and income values
            geojson=geojson_asset_path, # Your GeoJSON file with region shapes
            locations="AlueNimi", # Tells Plotly which column in income_df has the region names
            featureidkey="properties.nimi", # Tells Plotly where to find the matching region name within the GeoJSON's properties
            color=str(disp_year), # This column's values will determine the color
            color_continuous_scale="speed", # Uses the "Viridis" continuous color scale (low values are purple/blue, high values are yellow)
            range_color=(10000, 200000), 
            # --- End of key coloring part ---
            mapbox_style="carto-positron",
            zoom=9.7,
            center={"lat": 60.255541, "lon": 24.782289},
            opacity=0.7,
            labels={"2022"} # Makes the legend label clearer
        )
        
        # Optimize layout for performance
        fig.update_layout(
            margin={"r":0,"t":0,"l":0,"b":0},
            autosize=True,
            height=700,
        )
        
        return fig
    except Exception as e:
        print(f"Error creating map: {str(e)}")
        return px.scatter(title=f"Error creating map: {str(e)}")

# Callback for showing data table - simplified
@app.callback(
    Output('data-table-container', 'children'),
    Input('show-data-button', 'n_clicks')
)
def update_data_table(n_clicks):
    if n_clicks %2 == 0:
        return html.Div()
    
    if income_df is None:
        return html.Div("No data available")
    
    return html.Div([
        html.H4("Data Preview (First 20 Rows)"),
        dash.dash_table.DataTable(
            data=income_df.sort_values(by=['2022'],ascending=False).head(20).to_dict('records'),
            columns=[{'name': col, 'id': col} for col in income_df.columns],
            style_table={'overflowX': 'auto'},
            style_cell={
                'textAlign': 'left',
                'minWidth': '100px', 'width': '150px', 'maxWidth': '300px',
                'overflow': 'hidden',
                'textOverflow': 'ellipsis',
            }
        )
    ])

# Callback for showing memory usage
@app.callback(
    Output('memory-usage-container', 'children'),
    Input('show-memory-button', 'n_clicks')
)
def update_memory_usage(n_clicks):
    if n_clicks %2 == 0:
        return html.Div()
    
    if income_df is None:
        return html.Div("No data available")
    
    # Calculate file size of the optimized GeoJSON
    file_size_mb = os.path.getsize(geojson_path) / (1024*1024) if geojson_path else 0
    memory_usage_mb = income_df.memory_usage(deep=True).sum() / (1024*1024)
    
    return html.Div([
        html.H4("Data & Memory Usage"),
        html.P(f"Optimized GeoJSON file size: {file_size_mb:.2f} MB"),
        html.P(f"Income DataFrame memory usage: {memory_usage_mb:.2f} MB")
    ])

# Run the app
if __name__ == "__main__":
    app.run_server(debug=True)