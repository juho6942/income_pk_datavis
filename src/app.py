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
import scipy.stats as sps
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
app = dash.Dash(
    __name__, 
    title="Helsinki Region Income Map",
    external_stylesheets=[
        dbc.themes.FLATLY,  # A clean, modern theme
        "https://fonts.googleapis.com/css2?family=Lato:wght@400;700&family=Montserrat:wght@500;700&display=swap"
    ]
)
app.index_string = '''
<!DOCTYPE html>
<html>
    <head>
        {%metas%}
        <title>{%title%}</title>
        {%favicon%}
        {%css%}
        <style>
            body {
                font-family: 'Lato', sans-serif;
                background-color: #f8f9fa;
                color: #343a40;
            }
            h1, h2, h3, h4 {
                font-family: 'Montserrat', sans-serif;
                font-weight: 700;
            }
            .card {
                border-radius: 10px;
                box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
                margin-bottom: 20px;
            }
            .navbar-brand {
                font-weight: 700;
                font-size: 1.5rem;
            }
        </style>
    </head>
    <body>
        {%app_entry%}
        <footer>
            {%config%}
            {%scripts%}
            {%renderer%}
        </footer>
    </body>
</html>
'''
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
            layout=dict(title_text=f"{year}")
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
app.layout = dbc.Container([
    html.Br(),
    html.Div(
        html.H2(
            "Capital City Region Income Explorer",
            className="py-3 text-center text-white font-weight-bold",
            style={
                "backgroundColor": "#1B4D3E",
                "fontFamily": "'Montserrat', sans-serif",
                "margin": "0",
                "boxShadow": "0 2px 4px rgba(0,0,0,0.2)",
                "letterSpacing": "0.5px",
                "borderRadius": "12px",  # Added curved edges
                "padding": "10px 15px"
            }
        ),
        className="mb-4"
    ),
    
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardBody([
                    html.P(
                        "Explore median household income patterns across Helsinki, Espoo, and Vantaa from 2005-2023.",
                        className="card-text text-center text-muted mb-4"
                    ),
                    # Loading indicator
                    dcc.Loading(
                        id="loading-map",
                        type="circle",
                        children=[
                            # The map with animation controls
                            dcc.Graph(
                                id='income-map',
                                style={'height': '800px'},
                                config={
                                    'scrollZoom': True,
                                    'displayModeBar': True,
                                    'modeBarButtonsToRemove': ['lasso2d', 'select2d']
                                }
                            )
                        ]
                    ),
                ])
            ], className="mb-4"),
        ], width=12)
    ]),
    
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardBody([
                    html.H4("Area Comparison", className="card-title"),
                    html.P("Select areas to compare income trends over time:", className="text-muted"),
                    dbc.Row([
                        dbc.Col([
                            dcc.Dropdown(
                                id='area-input',
                                options=[{'label': area, 'value': area} for area in areanames],
                                multi=True,
                                value=['Jollas'],
                                placeholder="Select areas to compare...",
                                className="mb-3"
                            )
                        ], width=12)
                    ]),
                    dcc.Graph(
                        id='income-line-chart',
                        style={'height': '400px'}
                    )
                ])
            ], className="mb-4"),
        ], width=12)
    ]),
    
    # Data explorer section
    dbc.Row([
        dbc.Col([
            dbc.Card([
                dbc.CardBody([
                    html.H4("Data Explorer", className="card-title"),
                    html.P("View the trends and statistics of selected areas:", className="text-muted mb-3"),
                    dbc.Button(
                        "Toggle Data Table",
                        id='show-data-button',
                        color="secondary",
                        className="mb-3",
                        n_clicks=0,
                    ),
                    html.Div(id='data-table-container')
                ])
            ])
        ], width=12)
    ]),
    
    # Footer
    dbc.Row([
        dbc.Col([
            html.Hr(),
            html.P(
                "Helsinki Region Income Map Dashboard • Created with Dash",
                className="text-center text-muted"
            ),
        ], width=12)
    ], className="mt-4 mb-4")
    
], fluid=True, className="px-4")

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

@app.callback(
    Output('data-table-container', 'children'),
    Input('show-data-button', 'n_clicks'),
    Input('area-input', 'value'),
)
def update_data_table(n_clicks, areas):
    if n_clicks % 2 == 0:
        return html.Div()

    if income_df is None or areas is None:
        return html.Div("No data available")

    # Ensure list format
    area_names_selected = [areas] if isinstance(areas, str) else areas

    try:
        selected_data = data_pivoted[['Year'] + area_names_selected]
    except Exception as e:
        return html.Div(f"Error selecting data: {str(e)}")

    # Compute summary statistics per area
    summary_rows = []
    n_years = MAX_YEAR - MIN_YEAR

    for area in area_names_selected:
        series = selected_data[area]
        series = series.dropna()
        start_val = series.iloc[0]
        end_val = series.iloc[-1]

        if start_val > 0 and end_val > 0:
            cagr = ((end_val / start_val) ** (1 / n_years) - 1) * 100
        else:
            cagr = None

        trend = end_val - start_val
        best_year = selected_data.loc[series.idxmax(), 'Year']
        worst_year = selected_data.loc[series.idxmin(), 'Year']

        summary_rows.append({
            'Area': area,
            'CAGR (%)': f"{cagr:.2f}" if cagr is not None else "N/A",
            'Overall Growth (€)': f"{trend:,.0f}",
            'Best Year': best_year,
            'Worst Year': worst_year
        })
    renamed_data = selected_data.copy()
    
    renamed_data.columns = [
        'Year' if col == 'Year' else f"{col} Median household taxpayer income (€)"
        for col in renamed_data.columns
    ]
    for col in renamed_data.columns:
        if col != 'Year':
            renamed_data[col] = renamed_data[col].apply(
                lambda x: f"{x:,.0f}" if pd.notnull(x) else ""
            )

    return html.Div([
        html.Br(),
        html.H4("Summary Statistics"),
        dash.dash_table.DataTable(
            data=summary_rows,
            columns=[
                {'name': 'Area', 'id': 'Area'},
                {'name': 'CAGR (%)', 'id': 'CAGR (%)'},
                {'name': 'Overall Growth (€)', 'id': 'Overall Growth (€)'},
                {'name': 'Best Year', 'id': 'Best Year'},
                {'name': 'Worst Year', 'id': 'Worst Year'}
            ],
            style_table={'overflowX': 'auto'},
            style_cell={
                'textAlign': 'center',
                'minWidth': '100px', 'width': '150px', 'maxWidth': '300px',
                'overflow': 'hidden',
                'textOverflow': 'ellipsis',
            }
        ),
        html.Br(),
        html.H4("Selected Area Raw Data"),
        dash.dash_table.DataTable(
            id='raw-data-table',
            data=renamed_data.to_dict('records'),
            columns=[{'name': col, 'id': col} for col in renamed_data.columns],
            style_table={'overflowX': 'auto'},
            style_cell={'textAlign': 'left', 'padding': '5px'},
            style_header={
                'backgroundColor': 'rgb(230, 230, 230)'
            }
        )
    ])
if __name__ == '__main__':
    app.run_server(debug=True, port=8051) 