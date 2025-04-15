import streamlit as st
import pandas as pd
import geopandas as gpd
import plotly.express as px
import json
import os
from functools import lru_cache
from shapely.geometry import shape
import warnings

# --- Configuration ---
WFS_BASE_URL = "https://kartta.hel.fi/ws/geoserver/avoindata/wfs"
LAYER_NAME = "avoindata:Seutukartta_aluejako_pienalue"
OUTPUT_FORMAT = "application/json"
SOURCE_CRS = "EPSG:3879"
TARGET_CRS = "EPSG:4326"
MUNICIPALITY_CODES = {'091': 'Helsinki', '049': 'Espoo', '092': 'Vantaa'}
LOCATION_ID_COL = 'nimi'

# --- Cached Data Functions ---
@st.cache_data(ttl=3600)  # Cache for 1 hour
def load_geojson_data():
    """Load GeoJSON data with caching and error handling"""
    params = {
        'service': 'WFS', 
        'version': '2.0.0', 
        'request': 'GetFeature',
        'typeNames': LAYER_NAME, 
        'outputFormat': OUTPUT_FORMAT, 
        'srsName': SOURCE_CRS
    }
    
    import requests
    try:
        # Use json endpoint directly instead of reading as geodataframe first
        response = requests.get(WFS_BASE_URL, params=params)
        response.raise_for_status()
        geojson_data = response.json()
        
        # Return the data and no error
        return geojson_data, None
    except Exception as e:
        error_msg = f"Error loading data: {str(e)}"
        return None, error_msg

@st.cache_data(ttl=3600)  # Cache for 1 hour
def process_geojson(geojson_data):
    """Process GeoJSON data into a filtered & reprojected GeoDataFrame"""
    if not geojson_data:
        return None
    
    # Convert to GeoDataFrame more efficiently
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=RuntimeWarning)
        
        # Create GeoDataFrame from features
        features = geojson_data['features']
        
        # Extract properties and geometry separately
        properties = [feature['properties'] for feature in features]
        geometries = [shape(feature['geometry']) for feature in features]
        
        # Create GeoDataFrame
        gdf = gpd.GeoDataFrame(properties, geometry=geometries, crs=SOURCE_CRS)
        
        # Filter by municipality code (using 'kunta' column)
        if 'kunta' in gdf.columns:
            gdf = gdf[gdf['kunta'].astype(str).isin(MUNICIPALITY_CODES.keys())].copy()
        
        # Reproject to target CRS
        gdf = gdf.to_crs(TARGET_CRS)
        
        # Simplify geometries for better performance
        gdf['geometry'] = gdf['geometry'].simplify(tolerance=0.001, preserve_topology=True)
        
        return gdf

@st.cache_data(ttl=3600)  # Cache for 1 hour
def get_income_data():
    """Load income data with caching"""
    from funcs.get_inc_data import make_query
    from funcs.clean_data import clean_data
    
    try:
        inc_data = make_query(["2022"])
        return clean_data(inc_data)
    except Exception as e:
        st.error(f"Error loading income data: {str(e)}")
        return None

# Modified to avoid hashing issues with GeoDataFrames
def merge_data(gdf, income_data):
    """Merge geographic and income data - not cached due to GeoDataFrame unhashability"""
    if gdf is None or income_data is None:
        return None
    
    # Only keep needed columns from income data for merging
    income_cols = ['AlueNimi', '2022 Valtionveronalaisten tulojen keskiarvo, euroa']
    income_data_slim = income_data[income_cols].copy()
    
    # Merge datasets
    merged_gdf = pd.merge(
        gdf,
        income_data_slim, 
        left_on='nimi', 
        right_on='AlueNimi', 
        how='inner'
    )
    
    return merged_gdf

# Alternative approach using key identifiers for caching
@st.cache_data(ttl=3600)
def get_merged_data(gdf_json_str, income_data_json_str):
    """A cacheable version of merge data that works with string representations"""
    try:
        # Convert string back to GeoDataFrame
        gdf = gpd.GeoDataFrame.from_features(json.loads(gdf_json_str), crs=TARGET_CRS)
        # Convert string back to DataFrame
        income_data = pd.read_json(income_data_json_str)
        
        # Perform the merge
        merged_gdf = pd.merge(
            gdf,
            income_data, 
            left_on='nimi', 
            right_on='AlueNimi', 
            how='inner'
        )
        
        return merged_gdf
    except Exception as e:
        st.error(f"Error merging data: {str(e)}")
        return None

# --- Create Optimized GeoJSON for Plotting ---
def create_optimized_geojson(gdf):
    """Create a simplified and optimized GeoJSON for Plotly"""
    # Convert to GeoJSON format
    geojson_data = json.loads(gdf.to_json())
    
    # Reduce precision of coordinates to 5 decimal places (about 1 meter precision)
    for feature in geojson_data['features']:
        if feature['geometry']['type'] == 'Polygon':
            for ring in feature['geometry']['coordinates']:
                for coord in ring:
                    coord[0] = round(coord[0], 5)
                    coord[1] = round(coord[1], 5)
        elif feature['geometry']['type'] == 'MultiPolygon':
            for polygon in feature['geometry']['coordinates']:
                for ring in polygon:
                    for coord in ring:
                        coord[0] = round(coord[0], 5)
                        coord[1] = round(coord[1], 5)
    
    return geojson_data

# --- Main Application ---
def main():
    st.set_page_config(layout="wide", page_title="Helsinki Region Income Map")
    
    st.title("Helsinki Region Income Map")
    st.write("Displays average income data by Pienalue for Helsinki, Espoo, and Vantaa.")
    
    # Load data with progress indicators
    with st.spinner("Loading geographic data..."):
        geojson_data, error = load_geojson_data()
        
        if error:
            st.error(error)
            return
        
        if not geojson_data:
            st.warning("No data returned from the server.")
            return
            
        gdf = process_geojson(geojson_data)
        
        if gdf is None or gdf.empty:
            st.warning("No features found after filtering.")
            return
    
    # Load income data
    with st.spinner("Loading income data..."):
        income_data = get_income_data()
        
        if income_data is None:
            st.warning("Could not load income data.")
            return
    
    # Merge datasets - using direct merge (non-cached) to avoid hashing issues
    with st.spinner("Merging data..."):
        # Option 1: Direct merge without caching
        merged_gdf = merge_data(gdf, income_data)
        
        # Option 2: If you want caching, use the alternative approach with string representations
        # Convert dataframes to json strings for caching
        # gdf_json = gdf.to_json()
        # income_cols = ['AlueNimi', '2022 Valtionveronalaisten tulojen keskiarvo, euroa'] 
        # income_data_slim = income_data[income_cols].copy()
        # income_json = income_data_slim.to_json()
        # merged_gdf = get_merged_data(gdf_json, income_json)
        
        if merged_gdf is None or merged_gdf.empty:
            st.warning("No matching areas found when merging data.")
            return
            
        st.success(f"Successfully loaded and processed data for {len(merged_gdf)} areas.")
    
    # Display map
    with st.spinner("Generating map..."):
        try:
            # Calculate center for map view
            center_lat = merged_gdf.geometry.centroid.y.mean()
            center_lon = merged_gdf.geometry.centroid.x.mean()
            
            # Prepare optimized geojson for plotting
            plot_geojson = create_optimized_geojson(merged_gdf)
            
            # Create Plotly figure with optimized settings
            fig = px.choropleth_mapbox(
                merged_gdf,
                geojson=plot_geojson,
                locations=LOCATION_ID_COL,
                featureidkey=f"properties.{LOCATION_ID_COL}",
                color="2022 Valtionveronalaisten tulojen keskiarvo, euroa",
                color_continuous_scale="Viridis",
                range_color=(30000, 120000),  # More realistic range based on Finnish income
                mapbox_style="carto-positron",
                center={"lat": center_lat, "lon": center_lon},
                zoom=9,
                opacity=0.7,
                labels={"2022 Valtionveronalaisten tulojen keskiarvo, euroa": "Average Income (€)"},
                hover_data={
                    LOCATION_ID_COL: True,
                    "2022 Valtionveronalaisten tulojen keskiarvo, euroa": True
                }
            )
            
            # Optimize layout for performance
            fig.update_layout(
                margin={"r":0,"t":0,"l":0,"b":0},
                mapbox=dict(
                    bearing=0,
                    pitch=0,
                ),
                autosize=True,
                height=700,  # Fixed height for better performance
            )
            
            # Display the map
            st.plotly_chart(fig, use_container_width=True, height=700)
            
        except Exception as e:
            st.error(f"Error creating map: {str(e)}")
    
    # Add data exploration options
    with st.expander("Data Explorer"):
        if st.checkbox("Show Data Table"):
            display_cols = [col for col in merged_gdf.columns if col != 'geometry']
            st.dataframe(merged_gdf[display_cols].head(20))
            
        if st.checkbox("Show Memory Usage"):
            memory_usage_mb = merged_gdf.memory_usage(deep=True).sum() / (1024*1024)
            st.write(f"Memory usage: {memory_usage_mb:.2f} MB")

if __name__ == "__main__":
    main()