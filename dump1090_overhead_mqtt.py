import time
import requests
import json
import math
import paho.mqtt.client as mqtt

# --- CONFIGURATION ---
# home location lat/lon
HOME_LAT = 41.83221
HOME_LON = -72.7511054
MAX_DISTANCE_MILES = 2

# dump1090 JSON URL
# dump1090-fa git repo that will work for this: https://github.com/flightaware/dump1090.git
DUMP1090_URL = "http://localhost/aircraft.json"

# Virtual Radar JSON URL
VR_URL = "http://localhost:8083/VirtualRadar/aircraftlist.json"

# MQTT Broker Details
MQTT_BROKER = "homeassistant.iot"
MQTT_PORT = 1883
MQTT_TOPIC = "aircraft/overhead"
MQTT_CLIENT_ID = "dump1090_overhead_notifier"
MQTT_USER = "mqttuser"
MQTT_PASS = '949500'
# Polling Interval (in seconds)
POLL_INTERVAL = 5
# ---------------------

# Getting a useful string for airports can be difficult:
def get_airport(air_string):
    if ',' not in air_string:
        return air_string
    parts = air_string.rsplit(',')
    if parts[1] != "United States":
        return parts[1]
    if len(parts) == 3:
        output = parts[-2]
        output = output.strip()
        return output
    elif len(parts) == 2:
        parts2 = parts[-2].split()
        if len(parts2) == 2:
            output = parts2[1]
        else:
            output = parts2[0]
        return output

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
    client.username_pw_set(MQTT_USER, MQTT_PASS)
    
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
                response_vr = requests.get(VR_URL)
                if response_vr.status_code == 200:
                    data_vr = response_vr.json()
                    vr_list = data_vr.get("acList", [])

                if response.status_code == 200:
                    data = response.json()
                    aircraft_list = data.get("aircraft", [])
                    
                    current_seen_hexes = set()

                    for ac in aircraft_list:
                        ac_lat = ac.get("lat")
                        ac_lon = ac.get("lon")
                        hex_id = ac.get("hex")
                        flight = ac.get("flight", "Unknown").strip()
                        altitude = ac.get("alt_baro", ac.get("altitude", "unknown"))
                        for vr_flight in vr_list:
                            if vr_flight.get("Call") == flight:
                                ac_from = get_airport(vr_flight.get("From", "None"))
                                ac_to = get_airport(vr_flight.get("To", "None"))
                                op = vr_flight.get("Op", "Unknown").strip()

                        # We need both lat and lon coordinates to check distance
                        if ac_lat is not None and ac_lon is not None and hex_id:
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
                                        "from": ac_from,
                                        "to": ac_to,
                                        "op": op,
                                        "timestamp": time.time()
                                    }
                                    
                                    # Publish to MQTT
                                    json_payload = json.dumps(payload)
                                    print(json_payload)
                                    client.publish(MQTT_TOPIC, json_payload, qos=1)
                                    print(f"ALERT: Flight {flight} ({hex_id}) is overhead! Dist: {round(distance, 2)} mi, Alt: {altitude}")
                                    
                                    active_alerts[hex_id] = time.time()

                    # Clean up tracked hex IDs that left the radius
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
