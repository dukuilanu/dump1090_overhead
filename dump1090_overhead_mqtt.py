import time
import requests
import json
import math
import paho.mqtt.client as mqtt

# --- CONFIGURATION ---
# The lat/lon requested by the user
HOME_LAT = 41.83221
HOME_LON = -72.7511054
MAX_DISTANCE_MILES = 1.5

# dump1090 JSON URL (Change IP if dump1090 is running on a different machine)
DUMP1090_URL = "http://localhost/aircraft.json"

# MQTT Broker Details
MQTT_BROKER = "homeassistant.iot"
MQTT_PORT = 1883
MQTT_TOPIC = "aircraft/overhead"
MQTT_CLIENT_ID = "dump1090_overhead_notifier"

# Polling Interval (in seconds)
POLL_INTERVAL = 5
# ---------------------

def haversine_distance(lat1, lon1, lat2, lon2):
    """Calculate the great-circle distance between two points in miles."""
    R = 3958.8  # Earth radius in miles
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (math.sin(delta_phi / 2) ** 2 +
         math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("Connected to MQTT Broker successfully.")
    else:
        print(f"Failed to connect, return code {rc}")

def main():
    # Setup MQTT Client
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, MQTT_CLIENT_ID)
    client.on_connect = on_connect
    client.username_pw_set("mqttuser", "949500")
    
    client.connect(MQTT_BROKER, MQTT_PORT, 60)
    client.loop_start()

    # Track already alerted planes to prevent spamming while they are in the zone
    active_alerts = {}

    print(f"Starting dump1090 overhead tracking...")
    print(f"Target: Lat {HOME_LAT}, Lon {HOME_LON} | Radius: {MAX_DISTANCE_MILES} miles")

    try:
        while True:
            try:
                response = requests.get(DUMP1090_URL, timeout=3)
                if response.status_code == 200:
                    data = response.json()
                    aircraft_list = data.get("aircraft", [])
                    
                    current_seen_hexes = set()

                    for ac in aircraft_list:
                        ac_lat = ac.get("lat")
                        ac_lon = ac.get("lon")
                        hex_id = ac.get("hex")
                        flight = ac.get("flight", "UNKNOWN").strip()
                        altitude = ac.get("alt_baro", ac.get("altitude", "unknown"))

                        # We need both lat and lon coordinates to check distance
                        if ac_lat is not None and ac_lon is not None and altitude <=10000 and hex_id:
                            distance = haversine_distance(HOME_LAT, HOME_LON, ac_lat, ac_lon)

                            if distance <= MAX_DISTANCE_MILES:
                                current_seen_hexes.add(hex_id)
                                
                                # Send payload if it's a newly entered aircraft
                                if hex_id not in active_alerts:
                                    payload = {
                                        "hex": hex_id,
                                        "flight": flight,
                                        "distance_miles": round(distance, 2),
                                        "altitude_feet": altitude,
                                        "lat": ac_lat,
                                        "lon": ac_lon,
                                        "timestamp": time.time()
                                    }
                                    
                                    # Publish to MQTT
                                    json_payload = json.dumps(payload)
                                    print(json_payload)
                                    client.publish(MQTT_TOPIC, json_payload, qos=1)
                                    print(f"ALERT: Flight {flight} ({hex_id}) is overhead! Dist: {round(distance, 2)} mi, Alt: {altitude} ft")
                                    
                                    active_alerts[hex_id] = time.time()

                    # Clean up tracked hex IDs that left the 2-mile radius zone
                    for cached_hex in list(active_alerts.keys()):
                        if cached_hex not in current_seen_hexes:
                            print(f"Flight left overhead zone: {cached_hex}")
                            del active_alerts[cached_hex]

            except requests.exceptions.RequestException as e:
                print(f"Error reading dump1090 feed: {e}")

            time.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        print("Stopping tracker...")
    finally:
        client.loop_stop()
        client.disconnect()

if __name__ == "__main__":
    main()
