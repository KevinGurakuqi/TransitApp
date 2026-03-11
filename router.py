import requests
import json
import sys
import os
import math
import re

# Load .env from project root (never commit .env - use .env.example as a template)
from dotenv import load_dotenv
load_dotenv()

# Fix Windows console encoding for emojis
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        # Python < 3.7 fallback
        import codecs
        sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')

# 1. Google Maps API key - set GOOGLE_MAPS_API_KEY in .env or environment
#    Get one at: Google Cloud Console -> Credentials -> Create -> API Key
API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "")

# 2. Uber API (optional) - set in .env for real price estimates
#    UBER_SERVER_TOKEN or UBER_OAUTH_TOKEN from https://developer.uber.com/
UBER_SERVER_TOKEN = os.environ.get("UBER_SERVER_TOKEN", "")
UBER_OAUTH_TOKEN = os.environ.get("UBER_OAUTH_TOKEN", "")

def get_coordinates(address):
    """
    Geocode address to coordinates. Prefers the most precise result:
    - ROOFTOP or RANGE_INTERPOLATED (exact street address) over APPROXIMATE
    - Result that matches a street number if the user provided one
    """
    base_url = "https://maps.googleapis.com/maps/api/geocode/json"
    params = {
        "address": address,
        "key": API_KEY,
        "region": "ca"  # Prefer Canadian results
    }
    try:
        response = requests.get(base_url, params=params, timeout=10).json()
    except (requests.exceptions.RequestException, requests.exceptions.Timeout):
        return None

    if response.get('status') == 'REQUEST_DENIED':
        return None

    if response['status'] != 'OK' or not response.get('results'):
        return None

    results = response['results']
    # Extract street number from user input if present (e.g. "1624" from "1624 bloor st east")
    street_number_match = re.search(r'\b(\d+)\s+', address.strip())
    user_street_number = street_number_match.group(1) if street_number_match else None

    def score_result(r):
        """Higher = better (more precise, or matches street number)."""
        score = 0
        loc_type = r.get('geometry', {}).get('location_type', '')
        # Prefer precise location types
        if loc_type == 'ROOFTOP':
            score += 100
        elif loc_type == 'RANGE_INTERPOLATED':
            score += 80
        elif loc_type == 'GEOMETRIC_CENTER':
            score += 40
        # Prefer result whose formatted_address contains the user's street number
        fmt = r.get('formatted_address', '')
        if user_street_number and user_street_number in fmt:
            score += 50
        # Prefer street_address in types
        for c in r.get('address_components', []):
            if 'street_number' in c.get('types', []) and user_street_number:
                if c.get('long_name') == user_street_number or c.get('short_name') == user_street_number:
                    score += 60
                break
        if 'street_address' in r.get('types', []) or 'premise' in r.get('types', []):
            score += 30
        return score

    # When user gave a street number, prefer only ROOFTOP or RANGE_INTERPOLATED (pinpoint)
    if user_street_number:
        precise = [r for r in results if r.get('geometry', {}).get('location_type') in ('ROOFTOP', 'RANGE_INTERPOLATED')]
        candidates = precise if precise else results
    else:
        candidates = results

    best = max(candidates, key=score_result)
    location = best['geometry']['location']
    loc_type = best.get('geometry', {}).get('location_type', '')
    formatted_address = best.get('formatted_address', address)
    return {
        'coords': f"{location['lat']},{location['lng']}",
        'address': formatted_address,
        'lat': location['lat'],
        'lng': location['lng'],
        'location_type': loc_type,
    }

def get_route_data(start, end, mode="driving"):
    """Asks Google: How long to get from A to B using X mode?"""
    base_url = "https://maps.googleapis.com/maps/api/distancematrix/json"
    params = {
        "origins": start,
        "destinations": end,
        "mode": mode,
        "key": API_KEY
    }
    # If transit: subway, bus, train, rail (includes GO Train, TTC, etc.)
    if mode == "transit":
        params["transit_mode"] = "subway|bus|train|rail"

    try:
        response = requests.get(base_url, params=params, timeout=10).json()
    except (requests.exceptions.RequestException, requests.exceptions.Timeout) as e:
        # Error will be handled by returning None
        return None
    
    # Check for invalid API key
    if response.get('status') == 'REQUEST_DENIED':
        # Error will be handled by returning None
        return None
    
    if response['status'] == 'OK':
        element = response['rows'][0]['elements'][0]
        if element['status'] == 'OK':
            return {
                "distance_text": element['distance']['text'],
                "distance_value": element['distance']['value'], # Meters
                "duration_text": element['duration']['text'],
                "duration_value": element['duration']['value']  # Seconds
            }
    return None

def get_directions_routes(start_lat, start_lng, end_lat, end_lng, mode="transit", alternatives=True):
    """
    Gets detailed route information using Directions API.
    Returns multiple routes if alternatives=True.
    """
    base_url = "https://maps.googleapis.com/maps/api/directions/json"
    params = {
        "origin": f"{start_lat},{start_lng}",
        "destination": f"{end_lat},{end_lng}",
        "mode": mode,
        "key": API_KEY,
        "alternatives": "true" if alternatives else "false"
    }
    
    if mode == "transit":
        params["transit_mode"] = "subway|bus|train|rail"
    
    try:
        response = requests.get(base_url, params=params, timeout=10).json()
    except (requests.exceptions.RequestException, requests.exceptions.Timeout):
        return None
    
    if response.get('status') != 'OK':
        return None
    
    routes = []
    for route in response.get('routes', [])[:3]:  # Limit to 3 routes
        leg = route['legs'][0]
        route_info = {
            "distance_text": leg['distance']['text'],
            "distance_value": leg['distance']['value'],
            "duration_text": leg['duration']['text'],
            "duration_value": leg['duration']['value'],
            "steps": [],
            "transit_details": [],
            "alerts": []
        }
        
        # Extract transit steps and alerts
        for step in leg.get('steps', []):
            step_info = {
                "instruction": step.get('html_instructions', ''),
                "distance": step['distance']['text'],
                "duration": step['duration']['text'],
                "travel_mode": step.get('travel_mode', '')
            }
            
            # Check for transit details
            if 'transit_details' in step:
                transit = step['transit_details']
                step_info['transit'] = {
                    "line": transit.get('line', {}).get('name', ''),
                    "vehicle": transit.get('line', {}).get('vehicle', {}).get('name', ''),
                    "departure_stop": transit.get('departure_stop', {}).get('name', ''),
                    "arrival_stop": transit.get('arrival_stop', {}).get('name', ''),
                    "num_stops": transit.get('num_stops', 0)
                }
                
                # Check for alerts
                if 'line' in transit and 'agencies' in transit['line']:
                    for agency in transit['line'].get('agencies', []):
                        if 'url' in agency:  # Sometimes alerts are in agency info
                            pass
                
                route_info['transit_details'].append(step_info['transit'])
            
            route_info['steps'].append(step_info)
        
        # Check for transit alerts in the route
        if 'warnings' in route:
            # Filter out "walking directions are in beta" warnings
            filtered_warnings = [
                w for w in route['warnings'] 
                if 'beta' not in w.lower() and 'walking directions' not in w.lower()
            ]
            route_info['alerts'] = filtered_warnings
        
        # Add snow-related delays if it's winter (you can make this more sophisticated)
        import datetime
        current_month = datetime.datetime.now().month
        if current_month in [12, 1, 2, 3]:  # Winter months
            route_info['alerts'] = route_info.get('alerts', [])
            # Check if there are any delays that might be weather-related
            if 'delay' in str(route_info.get('alerts', [])).lower():
                route_info['alerts'].append('⚠️ Winter weather may cause transit delays and slower service')
        
        routes.append(route_info)
    
    return routes if routes else None

def get_walking_route(start_lat, start_lng, end_lat, end_lng):
    """Get walking route - only returns if duration < 1 hour"""
    routes = get_directions_routes(start_lat, start_lng, end_lat, end_lng, mode="walking", alternatives=False)
    if routes and routes[0]['duration_value'] < 3600:  # Less than 1 hour (3600 seconds)
        return routes[0]
    return None

def calculate_straight_distance(lat1, lon1, lat2, lon2):
    """Calculate straight-line distance between two coordinates in km (Haversine formula)"""
    R = 6371  # Earth's radius in km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a))
    return R * c

def get_uber_price_estimate(start_lat, start_lng, end_lat, end_lng):
    """
    Gets real Uber price estimates from Uber API.
    Returns dict with price info or None if unavailable.
    """
    # Try OAuth token first (more features), then server token
    token = UBER_OAUTH_TOKEN or UBER_SERVER_TOKEN
    
    if not token:
        return None
    
    # Try the standard Price Estimates endpoint first (GET /v1.2/estimates/price)
    # This is the most common endpoint for price estimates
    url = "https://api.uber.com/v1.2/estimates/price"
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept-Language": "en_US"
    }
    
    params = {
        "start_latitude": start_lat,
        "start_longitude": start_lng,
        "end_latitude": end_lat,
        "end_longitude": end_lng
    }
    
    try:
        # Try standard GET endpoint first (with short timeout for Uber)
        response = requests.get(url, headers=headers, params=params, timeout=5)
        
        # If that fails, try the Guest Trips endpoint as fallback
        if response.status_code == 404 or response.status_code == 403:
            url_guest = "https://api.uber.com/v1/guests/trips/estimates"
            headers_guest = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }
            payload = {
                "pickup": {
                    "latitude": start_lat,
                    "longitude": start_lng
                },
                "dropoff": {
                    "latitude": end_lat,
                    "longitude": end_lng
                }
            }
            response = requests.post(url_guest, headers=headers_guest, json=payload, timeout=5)
        
        if response.status_code != 200:
            # Return None to fall back to estimate
            return None
        
        data = response.json()
        
        # Handle standard /v1.2/estimates/price response format - UberX only (single passenger)
        if 'prices' in data and len(data['prices']) > 0:
            # Look for UberX (standard ride, single passenger)
            for price in data['prices']:
                display_name = price.get('display_name', '').lower()
                product_id = price.get('product_id', '').lower()
                if 'uberx' in display_name or 'uber x' in display_name or product_id == 'uberx':
                    return {
                        'low_estimate': price.get('low_estimate'),
                        'high_estimate': price.get('high_estimate'),
                        'currency': price.get('currency_code', 'CAD'),
                        'duration_estimate': price.get('duration'),  # seconds
                        'distance_estimate': price.get('distance')   # miles
                    }
            
            # Fallback: return the first available option
            if data['prices']:
                price = data['prices'][0]
                return {
                    'low_estimate': price.get('low_estimate'),
                    'high_estimate': price.get('high_estimate'),
                    'currency': price.get('currency_code', 'CAD'),
                    'duration_estimate': price.get('duration'),
                    'distance_estimate': price.get('distance')
                }
        
        # Handle Guest Trips Estimates response format
        elif 'trip' in data and 'fare' in data['trip']:
            fare = data['trip']['fare']
            return {
                'low_estimate': fare.get('low_estimate'),
                'high_estimate': fare.get('high_estimate'),
                'currency': fare.get('currency', 'CAD'),
                'duration_estimate': data['trip'].get('duration_estimate'),  # seconds
                'distance_estimate': data['trip'].get('distance_estimate')   # miles
            }
        elif 'trips' in data and len(data['trips']) > 0:
            # Alternative response format
            for trip in data['trips']:
                if trip.get('product_id') == 'uberX' or 'uberX' in trip.get('display_name', '').lower():
                    fare = trip.get('fare', {})
                    return {
                        'low_estimate': fare.get('low_estimate'),
                        'high_estimate': fare.get('high_estimate'),
                        'currency': fare.get('currency', 'CAD'),
                        'duration_estimate': trip.get('duration_estimate'),
                        'distance_estimate': trip.get('distance_estimate')
                    }
        
        return None
        
    except (requests.exceptions.RequestException, requests.exceptions.Timeout):
        return None
    except (KeyError, ValueError):
        return None

def estimate_uber_price(meters, seconds):
    """
    Calculates a rough UberX price (fallback if API unavailable).
    Formula: Base ($2.50) + Booking ($2.50) + ($0.80/km) + ($0.25/min)
    Single passenger / standard ride only.
    """
    km = meters / 1000
    minutes = seconds / 60
    
    base_fare = 5.00  # Base + Booking fee
    cost_per_km = 0.81
    cost_per_min = 0.28
    
    estimate = base_fare + (km * cost_per_km) + (minutes * cost_per_min)
    
    # Minimum fare check
    return max(estimate, 8.00)

# --- THE MAIN TEST LOOP ---
if __name__ == "__main__":
    print("--- 🚦 TRANSIT COMPARATOR MVP ---")
    start_loc = input("Enter Start Location (e.g., Union Station, Toronto): ")
    end_loc = input("Enter Destination (e.g., Yorkdale Mall): ")
    
    # 1. Geocode
    start_result = get_coordinates(start_loc)
    end_result = get_coordinates(end_loc)
    
    if start_result and end_result:
        # Show what addresses were found
        print(f"\n📍 Start: {start_result['address']}")
        print(f"📍 End: {end_result['address']}")
        
        # Check straight-line distance to catch geocoding errors
        straight_dist_km = calculate_straight_distance(
            start_result['lat'], start_result['lng'],
            end_result['lat'], end_result['lng']
        )
        
        if straight_dist_km > 100:
            print(f"\n⚠️  Warning: Locations are {straight_dist_km:.1f} km apart (straight-line).")
            print("   This seems unusually far. Please verify the addresses are correct.")
        
        start_coords = start_result['coords']
        end_coords = end_result['coords']
        
        # 2. Get Driving Data
        drive_data = get_route_data(start_coords, end_coords, mode="driving")
        
        # 3. Get Transit Data
        transit_data = get_route_data(start_coords, end_coords, mode="transit")
        
        print("\n--- RESULTS ---")
        
        if drive_data:
            # Try to get real Uber pricing first
            uber_data = get_uber_price_estimate(
                start_result['lat'], start_result['lng'],
                end_result['lat'], end_result['lng']
            )
            
            print(f"🚗 RIDE SHARE (Uber/Lyft):")
            print(f"   Time:  {drive_data['duration_text']}")
            print(f"   Dist:  {drive_data['distance_text']}")
            
            if uber_data:
                # Real Uber API data
                if uber_data.get('low_estimate') and uber_data.get('high_estimate'):
                    print(f"   Uber Price: ${uber_data['low_estimate']:.2f} - ${uber_data['high_estimate']:.2f} {uber_data.get('currency', 'CAD')}")
                elif uber_data.get('low_estimate'):
                    print(f"   Uber Price: ~${uber_data['low_estimate']:.2f} {uber_data.get('currency', 'CAD')}")
                else:
                    # Fallback to estimate
                    uber_price = estimate_uber_price(drive_data['distance_value'], drive_data['duration_value'])
                    print(f"   Est Price: ${uber_price:.2f} (estimated)")
            else:
                # Fallback to estimate calculation
                uber_price = estimate_uber_price(drive_data['distance_value'], drive_data['duration_value'])
                print(f"   Est Price: ${uber_price:.2f} (estimated - no Uber API token configured)")
        
        if transit_data:
            print(f"\n🚌 PUBLIC TRANSIT:")
            print(f"   Time:  {transit_data['duration_text']}")
            print(f"   Dist:  {transit_data['distance_text']}")
            print(f"   Price: $3.30 (Standard Fare)") # Hardcoded for MVP
            
    else:
        print("Error: Could not find those addresses.")