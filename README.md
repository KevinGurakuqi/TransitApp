# Transit Comparator Web App

A web application that compares ride-share (Uber/Lyft) prices and public transit options for any route.

## Features

- 🚗 Real-time Uber price estimates (when API token is configured)
- 🚌 Public transit time and distance
- 📍 Address geocoding with location verification
- ⚠️ Distance warnings for unusual routes
- 💰 Price comparison between ride-share and transit

## Setup

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure API Keys:**
   - Open `router.py`
   - Add your Google Maps API key (required)
   - Optionally add your Uber API token for real pricing

3. **Run the web app:**
   ```bash
   python app.py
   ```

4. **Open in browser:**
   - Navigate to `http://localhost:5000`

## API Keys Required

### Google Maps API (Required)
- Get your API key from [Google Cloud Console](https://console.cloud.google.com/)
- Enable "Geocoding API" and "Distance Matrix API"
- Add the key to `router.py` line 18

### Uber API (Optional)
- Get your token from [Uber Developer Dashboard](https://developer.uber.com/)
- Create an app and get a Server Token
- Add the token to `router.py` line 36
- Without this, the app will use estimated pricing

## Usage

1. Enter a start location (e.g., "Union Station, Toronto")
2. Enter a destination (e.g., "Yorkdale Mall, Toronto")
3. Click "Compare Routes"
4. View the comparison of ride-share vs public transit

## Files

- `app.py` - Flask web application
- `router.py` - Core routing and API logic
- `templates/index.html` - Web interface
- `static/style.css` - Styling

## Development

The app runs in debug mode by default. For production, set `debug=False` in `app.py`.
