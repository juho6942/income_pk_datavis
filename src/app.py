import dash
from dash import dcc, html, Input, Output, Patch, State
import pandas as pd
import geopandas as gpd
import plotly.express as px
import plotly.graph_objects as go
import json
import requests
from shapely.geometry import shape
import warnings
from functools import lru_cache
import os
from funcs.get_inc_data import make_query
from funcs.clean_data import clean_data
import dash_bootstrap_components as dbc

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
    #print(income_data.columns)
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

# Create and cache the initial map with animation frames
def create_animated_map():
    """Create a map with animation frames for all years"""
    
    if geojson_path is None or income_df is None:
        return px.scatter(title="Error loading data")
    
    # Load GeoJSON from file to ensure it's available
    try:
        with open(geojson_path, 'r') as f:
            geojson_data = json.load(f)
    except Exception as e:
        print(f"Error loading GeoJSON: {str(e)}")
        return px.scatter(title=f"Error loading GeoJSON: {str(e)}")
    
    # Create a base figure
    fig = go.Figure()
    
    # Create frames for each year
    frames = []
    
    # Add a choropleth trace for each year
    base_trace = go.Choroplethmapbox(
        geojson=geojson_data,
        locations=income_df['AlueNimi'],
        z=income_df[str(MAX_YEAR)],
        featureidkey="properties.nimi",
        colorscale="speed",
        zmin=10000,
        zmax=200000,
        marker_opacity=0.7,
        marker_line_width=0,
        colorbar=dict(
            title="Median household income",
            thickness=15,
            len=0.9,
            y=0.5,
            yanchor="middle",
            outlinewidth=0
        ),
        hovertemplate='<b>%{location}</b><br>Income %{z:,.0f} €<extra></extra>',
    )

    # Create the figure with the base trace
    fig = go.Figure(data=[base_trace])

    # Create animation frames with only updated 'z' values
    frames = []
    for year in AVAILABLE_YEARS:
        frames.append(go.Frame(
            data=[go.Choroplethmapbox(
                z=income_df[str(year)],
                locations=income_df['AlueNimi']
            )],
            name=str(year),
            layout=dict(title_text=f"Helsinki Region Income Map - {year}")
        ))
    fig.frames = frames

    # Define slider steps
    sliders = [{
        'active': len(AVAILABLE_YEARS) - 1,
        'yanchor': 'top',
        'xanchor': 'left',
        'currentvalue': {
            'font': {'size': 16},
            'prefix': 'Year: ',
            'visible': True,
            'xanchor': 'right'
        },
        'transition': {'duration': 0},
        'pad': {'b': 10, 't': 50},
        'len': 0.9,
        'x': 0.1,
        'y': 0,
        'steps': [
            {
                'args': [
                    [str(year)],
                    {
                        'frame': {'duration': 0, 'redraw': True},
                        'mode': 'immediate',
                        'transition': {'duration': 0}
                    }
                ],
                'label': str(year),
                'method': 'animate'
            }
            for year in AVAILABLE_YEARS
        ]
    }]

    # Define play/pause buttons
    updatemenus = [{
        'buttons': [
            {
                'args': [
                    None,
                    {
                        'frame': {'duration': 1000, 'redraw': True},
                        'fromcurrent': True,
                        'transition': {'duration': 0}
                    }
                ],
                'label': 'Play',
                'method': 'animate'
            },
            {
                'args': [
                    [None],
                    {
                        'frame': {'duration': 0, 'redraw': True},
                        'mode': 'immediate',
                        'transition': {'duration': 0}
                    }
                ],
                'label': 'Pause',
                'method': 'animate'
            }
        ],
        'direction': 'left',
        'pad': {'r': 10, 't': 87},
        'showactive': False,
        'type': 'buttons',
        'x': 0.1,
        'xanchor': 'right',
        'y': 0,
        'yanchor': 'top'
    }]

    # Final layout update
    fig.update_layout(
        title_text=f"Helsinki Region Income Map - {MAX_YEAR}",
        title_x=0.5,
        mapbox=dict(
            style="carto-positron",
            center={"lat": 60.255541, "lon": 24.782289},
            zoom=9.7
        ),
        height=700,
        margin={"r": 0, "t": 50, "l": 0, "b": 0},
        updatemenus=updatemenus,
        sliders=sliders
    )

    return fig
areanames = income_df['AlueNimi'].unique().tolist()
data = income_df.copy()
data_pivoted = data.transpose()
data_pivoted.columns = data_pivoted.iloc[-1]
data_pivoted.drop(data_pivoted.index[-1], inplace=True)
data_pivoted.reset_index(inplace=True)
data_pivoted.rename(columns={'index': 'Year'}, inplace=True)
print(data_pivoted.head())
# App Layout
app.layout = html.Div([
    html.H1("Helsinki Region Income Map", style={'textAlign': 'center'}),
    html.P("Displays Median household income of taxpayers by region for Helsinki, Espoo, and Vantaa.", style={'textAlign': 'center'}),
    
    # Loading indicator
    dcc.Loading(
        id="loading-map",
        type="default",
        children=[
            # The map with animation controls
            dcc.Graph(
                id='income-map',
                style={'height': '700px'},
                config={
                    'scrollZoom': True,
                    'displayModeBar': True,
                    'modeBarButtonsToRemove': ['lasso2d', 'select2d']
                }
            )
        ]
    ),
    dbc.Row([
        dbc.Col([dcc.Dropdown(areanames,multi=True, id='area-input', value='Jollas')], width=4)], style={'marginTop': '40px'})
    ,
    html.Div([
        dcc.Graph(
            id='income-line-chart',
            style={'height': '400px'}
        )
    ], style={'marginTop': '40px'}),
    # Data explorer section
    html.Div([
        html.H3("Data Explorer"),
        html.Button('Show Data Table', id='show-data-button', n_clicks=0),
        html.Div(id='data-table-container'),
    ], style={'marginTop': '20px'})
])

# Callback to initialize the map
@app.callback(
    Output('income-map', 'figure'),
    Input('income-map', 'id')  # Dummy input to trigger on load
)
def init_map(_):
    return create_animated_map()


@app.callback(
    Output('income-line-chart', 'figure'),
    Input('area-input', 'value'),
)
def update_line_chart(area_names_selected):
    
    
    
    fig = go.Figure()
    if not isinstance(area_names_selected, list):
        area_names_selected = [area_names_selected]
    
    # Add trace for each selected area
    for area in area_names_selected:
        if area in data_pivoted.columns:
            fig.add_trace(go.Scatter(
                x=AVAILABLE_YEARS,
                y=data_pivoted[area],
                mode='lines+markers',
                name=area
            ))
    
    # Set chart title
    title = f"Income Trends for {', '.join(area_names_selected)}"
    
    # Update layout
    fig.update_layout(
        title=title,
        xaxis_title='Year',
        yaxis_title='Median household income',
        hovermode='x unified',
        xaxis=dict(
            tickmode='array',
            tickvals=AVAILABLE_YEARS,
            ticktext=AVAILABLE_YEARS,
        ),
        yaxis=dict(
            tickprefix='€',
            tickformat=',.0f'
        )
    )

    return fig
    
# Callback for showing data table - unchanged
@app.callback(
    Output('data-table-container', 'children'),
    Input('show-data-button', 'n_clicks'),
    Input('area-input', 'value'),
)
def update_data_table(n_clicks, areas):
    if n_clicks % 2 == 0:
        return html.Div()
    
    if income_df is None:
        return html.Div("No data available")
    
    # Properly handle areas whether it's a string or a list
    if areas is None:
        return html.Div("No areas selected")
    
    area_names_selected = [areas] if isinstance(areas, str) else areas
    
    # Ensure we have a DataFrame with the selected columns
    area_names_selected.append('Year')
    try:
        selected_areas = data_pivoted[area_names_selected]
        
    except Exception as e:
        return html.Div(f"Error selecting data: {str(e)}")
    
    return html.Div([
        html.H4("Data View"),
        dash.dash_table.DataTable(
            data=selected_areas.head(20).to_dict('records'),  # 'records' is the correct format
            columns=[{'name': col, 'id': col} for col in selected_areas.columns[::-1]],
            style_table={'overflowX': 'auto'},
            style_cell={
                'textAlign': 'left',
                'minWidth': '100px', 'width': '150px', 'maxWidth': '300px',
                'overflow': 'hidden',
                'textOverflow': 'ellipsis',
            }
        )
    ])

if __name__ == '__main__':
    app.run_server(debug=True, port=8051) 