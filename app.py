from flask import Flask, render_template, request, jsonify
from router import (
    get_coordinates, 
    get_route_data, 
    get_directions_routes,
    get_walking_route,
    get_uber_price_estimate,
    estimate_uber_price,
    calculate_straight_distance,
    API_KEY
)

app = Flask(__name__)

# Pass API key to template
@app.context_processor
def inject_api_key():
    return dict(google_maps_api_key=API_KEY)

@app.route('/')
def index():
    """Main page"""
    return render_template('index.html')

@app.route('/health')
def health():
    """Health check endpoint"""
    return jsonify({'status': 'ok'}), 200

@app.route('/api/check-map-key')
def check_map_key():
    """Diagnostic endpoint to check if Maps API key is working"""
    return jsonify({
        'api_key_configured': bool(API_KEY),
        'api_key_preview': API_KEY[:10] + '...' if API_KEY else None,
        'instructions': {
            'step1': 'Go to https://console.cloud.google.com/apis/credentials',
            'step2': 'Click on your API key',
            'step3': 'Check "Application restrictions" - should be "None" or include "localhost"',
            'step4': 'Check "API restrictions" - should include "Maps JavaScript API"',
            'step5': 'Ensure billing is enabled for your Google Cloud project'
        }
    }), 200

@app.route('/share/<path:encoded_route>')
def share_route(encoded_route):
    """Share route page - decodes route parameters and displays comparison"""
    from urllib.parse import unquote
    try:
        # Decode the route parameters
        decoded = unquote(encoded_route)
        # For now, just redirect to main page with parameters
        # In a full implementation, you'd parse and display the route
        return render_template('index.html')
    except:
        return render_template('index.html')

@app.route('/api/compare', methods=['POST'])
def compare_routes():
    """API endpoint to compare transit options"""
    import time
    start_time = time.time()
    try:
        data = request.json
        start_loc = data.get('start')
        end_loc = data.get('end')
        
        if not start_loc or not end_loc:
            return jsonify({'error': 'Start and end locations are required'}), 400
        
        # Geocode addresses
        start_result = get_coordinates(start_loc)
        end_result = get_coordinates(end_loc)
        
        if not start_result or not end_result:
            return jsonify({
                'error': 'Could not find one or both addresses. Please try more specific addresses.'
            }), 400
        
        # Check distance warning
        straight_dist_km = calculate_straight_distance(
            start_result['lat'], start_result['lng'],
            end_result['lat'], end_result['lng']
        )
        
        warning = None
        if straight_dist_km > 100:
            warning = f"Locations are {straight_dist_km:.1f} km apart. Please verify addresses are correct."
        
        # Get route data
        start_coords = start_result['coords']
        end_coords = end_result['coords']
        
        drive_data = get_route_data(start_coords, end_coords, mode="driving")
        transit_data = get_route_data(start_coords, end_coords, mode="transit")
        
        # Get multiple transit routes and detailed info (may fail if Directions API restricted)
        try:
            transit_routes = get_directions_routes(
                start_result['lat'], start_result['lng'],
                end_result['lat'], end_result['lng'],
                mode="transit",
                alternatives=True
            )
        except Exception:
            transit_routes = None
        
        # Get walking route (only if < 1 hour)
        walking_data = get_walking_route(
            start_result['lat'], start_result['lng'],
            end_result['lat'], end_result['lng']
        )
        
        result = {
            'start_address': start_result['address'],
            'end_address': end_result['address'],
            'start_location_type': start_result.get('location_type', ''),
            'end_location_type': end_result.get('location_type', ''),
            'start_coords': {
                'lat': start_result['lat'],
                'lng': start_result['lng']
            },
            'end_coords': {
                'lat': end_result['lat'],
                'lng': end_result['lng']
            },
            'warning': warning,
            'ride_share': None,
            'transit': None,
            'transit_routes': None,
            'walking': None,
            'transit_alerts': []
        }
        
        # Process ride share data (single passenger / UberX only)
        if drive_data:
            # Get Uber data with timeout - don't wait too long
            try:
                uber_data = get_uber_price_estimate(
                    start_result['lat'], start_result['lng'],
                    end_result['lat'], end_result['lng']
                )
            except Exception:
                uber_data = None  # Fall back to estimate if Uber API fails
            
            ride_share = {
                'time': drive_data['duration_text'],
                'distance': drive_data['distance_text'],
                'price': None,
                'price_type': 'estimated'
            }
            
            if uber_data:
                if uber_data.get('low_estimate') and uber_data.get('high_estimate'):
                    ride_share['price'] = f"${uber_data['low_estimate']:.2f} - ${uber_data['high_estimate']:.2f}"
                    ride_share['price_type'] = 'real'
                    ride_share['currency'] = uber_data.get('currency', 'CAD')
                elif uber_data.get('low_estimate'):
                    ride_share['price'] = f"~${uber_data['low_estimate']:.2f}"
                    ride_share['price_type'] = 'real'
                    ride_share['currency'] = uber_data.get('currency', 'CAD')
                else:
                    uber_price = estimate_uber_price(drive_data['distance_value'], drive_data['duration_value'])
                    ride_share['price'] = f"${uber_price:.2f}"
            else:
                uber_price = estimate_uber_price(drive_data['distance_value'], drive_data['duration_value'])
                ride_share['price'] = f"${uber_price:.2f}"
            
            result['ride_share'] = ride_share
        
        # Process transit data
        if transit_data:
            result['transit'] = {
                'time': transit_data['duration_text'],
                'distance': transit_data['distance_text'],
                'price': '$3.30',
                'price_note': 'Standard Fare'
            }

        def _transit_price_for_route(route):
            """$10.50 if route uses GO Train/rail, else $3.30 (TTC standard)."""
            for detail in route.get('transit_details', []):
                vehicle = (detail.get('vehicle') or '').lower()
                line = (detail.get('line') or '').lower()
                if 'train' in vehicle or 'rail' in vehicle or 'go' in line:
                    return '$10.50'
            return '$3.30'

        # Process multiple transit routes (always build a list when we have transit)
        result['transit_routes'] = []
        all_alerts = []
        if transit_routes:
            for i, route in enumerate(transit_routes):
                route_info = {
                    'index': i + 1,
                    'time': route['duration_text'],
                    'distance': route['distance_text'],
                    'price': _transit_price_for_route(route),
                    'transit_details': route.get('transit_details', []),
                    'num_transfers': len([s for s in route.get('steps', []) if s.get('transit')])
                }
                result['transit_routes'].append(route_info)
                if route.get('alerts'):
                    all_alerts.extend(route['alerts'])
        elif transit_data:
            # Fallback: one route from Distance Matrix when Directions API returns nothing
            result['transit_routes'] = [{
                'index': 1,
                'time': transit_data['duration_text'],
                'distance': transit_data['distance_text'],
                'price': '$3.30',
                'transit_details': [],
                'num_transfers': 0
            }]

        if all_alerts or result['transit_routes']:
            filtered_alerts = [
                a for a in all_alerts
                if a and 'beta' not in str(a).lower() and 'walking directions' not in str(a).lower()
            ]
            import datetime
            current_month = datetime.datetime.now().month
            if current_month in [12, 1, 2, 3] and filtered_alerts:
                filtered_alerts.append('⚠️ Winter weather may cause transit delays and slower service')
            result['transit_alerts'] = list(set(filtered_alerts))
        
        # Process walking data
        if walking_data:
            result['walking'] = {
                'time': walking_data['duration_text'],
                'distance': walking_data['distance_text'],
                'price': 'Free'
            }
        
        return jsonify(result)
        
    except Exception as e:
        return jsonify({'error': f'An error occurred: {str(e)}'}), 500

if __name__ == '__main__':
    import sys
    port = 5000
    if len(sys.argv) > 1:
        port = int(sys.argv[1])
    print(f"Starting server on http://localhost:{port}")
    print("Press Ctrl+C to stop")
    app.run(debug=True, host='127.0.0.1', port=port, threaded=True)
