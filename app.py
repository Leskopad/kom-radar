import streamlit as st
import requests
import pandas as pd
import json
import os

CLIENT_ID = st.secrets["CLIENT_ID"]
CLIENT_SECRET = st.secrets["CLIENT_SECRET"]
REFRESH_TOKEN = st.secrets["REFRESH_TOKEN"]

CACHE_FILE = "segment_cache.json"


def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_cache(cache):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f)


def get_access_token():
    token_response = requests.post(
        "https://www.strava.com/oauth/token",
        data={
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "grant_type": "refresh_token",
            "refresh_token": REFRESH_TOKEN
        }
    )
    token_data = token_response.json()

    if "access_token" not in token_data:
        raise Exception(f"Token error: {token_data}")

    return token_data["access_token"]


def xom_to_seconds(xom_time):
    if not xom_time:
        return None

    xom_time = xom_time.strip()

    if xom_time.endswith("s"):
        return int(xom_time.replace("s", ""))

    parts = xom_time.split(":")
    if len(parts) == 2:
        return int(parts[0]) * 60 + int(parts[1])
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])

    return None


def seconds_to_pretty(seconds):
    if seconds is None:
        return "Unavailable"

    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def rank_to_number(rank_value):
    if isinstance(rank_value, int):
        return rank_value
    if isinstance(rank_value, float) and rank_value.is_integer():
        return int(rank_value)
    if isinstance(rank_value, str):
        if rank_value == "1*":
            return 1
        if rank_value.isdigit():
            return int(rank_value)
    return None


def rank_badge(rank_value):
    rank_num = rank_to_number(rank_value)

    if rank_num == 1:
        return "👑"
    if rank_num in [2, 3]:
        return "🥉"
    if rank_num is not None and rank_num <= 10:
        return "🔥"
    return ""


def style_rank_cell(value):
    rank_num = rank_to_number(value)

    if rank_num == 1:
        return "background-color: #f4c542; color: black; font-weight: bold;"
    if rank_num in [2, 3]:
        return "background-color: #9be7a7; color: black; font-weight: bold;"
    if rank_num is not None and rank_num <= 10:
        return "background-color: #a8d8ff; color: black; font-weight: bold;"
    return ""


def difficulty_label(gap_percent):
    if gap_percent <= 5:
        return "🟢 Very doable"
    if gap_percent <= 12:
        return "🟡 Stretch"
    return "🔴 Tough"


st.set_page_config(page_title="KOM Radar", layout="wide")
st.title("KOM Radar")
st.caption("Find the best Strava segments from a ride to target next.")

try:
    access_token = get_access_token()
except Exception as e:
    st.error(str(e))
    st.stop()

headers = {"Authorization": f"Bearer {access_token}"}

# recent rides for dropdown
activities_url = "https://www.strava.com/api/v3/athlete/activities"
activities_response = requests.get(activities_url, headers=headers)

if activities_response.status_code != 200:
    st.error(f"Could not load rides: {activities_response.text}")
    st.stop()

activities = activities_response.json()
ride_activities = [a for a in activities if a.get("sport_type") in ["Ride", "Run"]]

ride_options = {}
for a in ride_activities:
    label = f"{a['name']} | {a['start_date_local'][:10]} | {round(a['distance']/1000, 1)} km | {a['sport_type']}"
    ride_options[label] = str(a["id"])

selected_label = st.selectbox("Choose a recent ride", list(ride_options.keys()))

manual_activity_id = st.text_input("Or paste an Activity ID (optional)")
selected_activity_id = manual_activity_id.strip() if manual_activity_id.strip() else ride_options[selected_label]

col1, col2, col3 = st.columns(3)
with col1:
    max_segments = st.number_input("Max segments", min_value=10, max_value=300, value=50, step=10)
with col2:
    min_distance_km = st.number_input("Min distance (km)", min_value=0.0, max_value=20.0, value=0.5, step=0.1)
with col3:
    climbs_only = st.checkbox("Climbs only", value=False)

activity_url = f"https://www.strava.com/api/v3/activities/{selected_activity_id}?include_all_efforts=true"
activity_response = requests.get(activity_url, headers=headers)

st.write("Activity status code:", activity_response.status_code)

if activity_response.status_code != 200:
    st.error(activity_response.text)
    st.stop()

activity = activity_response.json()
efforts = activity.get("segment_efforts", [])

if not efforts:
    st.warning("No segment efforts found on this activity.")
    st.stop()

cache = load_cache()
rows = []

progress_text = st.empty()
progress_bar = st.progress(0)

efforts_to_check = efforts[:max_segments]
total_efforts = len(efforts_to_check)

for i, effort in enumerate(efforts_to_check):
    segment_id = str(effort["segment"]["id"])

    progress_text.write(f"Checking segment {i + 1} of {total_efforts}")
    progress_bar.progress((i + 1) / total_efforts)

    if segment_id in cache:
        segment = cache[segment_id]
    else:
        segment_url = f"https://www.strava.com/api/v3/segments/{segment_id}"
        segment_response = requests.get(segment_url, headers=headers)

        if segment_response.status_code != 200:
            continue

        segment = segment_response.json()
        cache[segment_id] = segment

    your_pr = segment.get("athlete_segment_stats", {}).get("pr_elapsed_time")
    kom_string = segment.get("xoms", {}).get("kom")
    kom_seconds = xom_to_seconds(kom_string)

    if your_pr is None or kom_seconds is None:
        continue

    distance_m = segment.get("distance", 0)
    distance_km = round(distance_m / 1000, 2)
    elev_gain = round(segment.get("total_elevation_gain", 0), 1)
    avg_grade = round(segment.get("average_grade", 0), 1)

    if distance_km < min_distance_km:
        continue

    if climbs_only and avg_grade <= 0:
        continue

    gap_seconds = your_pr - kom_seconds
    gap_percent = round(((your_pr - kom_seconds) / kom_seconds) * 100, 1)

    your_speed_kmh = round((distance_m / your_pr) * 3.6, 1) if your_pr > 0 else None
    kom_speed_kmh = round((distance_m / kom_seconds) * 3.6, 1) if kom_seconds > 0 else None

    if your_speed_kmh is not None and kom_speed_kmh is not None and kom_speed_kmh > 0:
        speed_gap_percent = round(((kom_speed_kmh - your_speed_kmh) / kom_speed_kmh) * 100, 1)
    else:
        speed_gap_percent = None

    kom_holder = "Unavailable"
    xoms = segment.get("xoms", {})
    if isinstance(xoms, dict):
        destination = xoms.get("destination", {})
        if isinstance(destination, dict):
            kom_holder = destination.get("name", "Unavailable")

    if gap_seconds == 0:
        kom_rank_value = "1*"
    else:
        kom_rank_value = effort.get("kom_rank") if effort.get("kom_rank") is not None else "Unavailable"

    pr_rank_value = effort.get("pr_rank") if effort.get("pr_rank") is not None else "Unavailable"

    rows.append({
        "Badge": rank_badge(kom_rank_value),
        "Segment": segment.get("name"),
        "Distance (km)": distance_km,
        "Avg Grade (%)": avg_grade,
        "Elev Gain (m)": elev_gain,
        "Your PR": seconds_to_pretty(your_pr),
        "KOM": seconds_to_pretty(kom_seconds),
        "Gap (s)": gap_seconds,
        "Gap to KOM (%)": gap_percent,
        "Your Speed": your_speed_kmh,
        "KOM Speed": kom_speed_kmh,
        "Speed Gap (%)": speed_gap_percent,
        "Riders": int(segment.get("athlete_count", 0)),
        "Total Efforts": int(segment.get("effort_count", 0)),
        "Difficulty": difficulty_label(gap_percent),
        "KOM Holder": kom_holder,
        "KOM Rank": kom_rank_value,
        "PR Rank": pr_rank_value,
        "Open Segment": f"https://www.strava.com/segments/{segment_id}"
    })

save_cache(cache)

progress_text.empty()
progress_bar.empty()

if not rows:
    st.warning("No usable segment data found.")
    st.stop()

df = pd.DataFrame(rows)
df = df.sort_values(by=["Gap to KOM (%)", "Gap (s)"], ascending=[True, True]).reset_index(drop=True)

if any(rank_to_number(v) == 1 for v in df["KOM Rank"]):
    st.success("You already own a KOM on this route 👑")

st.subheader("Top Targets")

top_row = df.iloc[0]
c1, c2, c3 = st.columns(3)

with c1:
    st.metric("🎯 Best Target", top_row["Segment"])

with c2:
    st.metric("Your PR vs KOM", f"{top_row['Your PR']} vs {top_row['KOM']}")

with c3:
    st.metric("Gap to KOM", f"{top_row['Gap to KOM (%)']}%")

st.subheader("All Segment Targets")

display_df = df[[
    "Badge",
    "Segment",
    "Distance (km)",
    "Avg Grade (%)",
    "Elev Gain (m)",
    "Your PR",
    "KOM",
    "Gap (s)",
    "Gap to KOM (%)",
    "Your Speed",
    "KOM Speed",
    "Speed Gap (%)",
    "Riders",
    "Total Efforts",
    "Difficulty",
    "KOM Holder",
    "KOM Rank",
    "PR Rank",
    "Open Segment"
]]

styled_df = (
    display_df.style
    .map(style_rank_cell, subset=["KOM Rank"])
    .format({
        "Distance (km)": "{:.2f}",
        "Avg Grade (%)": "{:.1f}",
        "Elev Gain (m)": "{:.1f}",
        "Gap (s)": "{:.0f}",
        "Gap to KOM (%)": "{:.1f}",
        "Your Speed": "{:.1f}",
        "KOM Speed": "{:.1f}",
        "Speed Gap (%)": "{:.1f}",
        "Riders": "{:.0f}",
        "Total Efforts": "{:.0f}",
    })
)

st.dataframe(
    styled_df,
    use_container_width=True,
    column_config={
        "Open Segment": st.column_config.LinkColumn(
            "Open Segment",
            display_text="Open"
        )
    },
    hide_index=True
)