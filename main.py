import os
os.environ['KIVY_NO_ARGS'] = '1'

import sqlite3
import datetime
import math
import hashlib
import threading
import time
import urllib.request
import json
import shutil

from kivy.app import App
from kivy.metrics import dp, sp
from kivy.clock import Clock, mainthread
from kivy.uix.screenmanager import ScreenManager, Screen, FadeTransition
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget
from kivy.uix.behaviors import ButtonBehavior
from kivy.graphics import Color, RoundedRectangle, Line, Ellipse
from kivy.network.urlrequest import UrlRequest

# Real map widget
from kivy_garden.mapview import MapView, MapMarker, MapLayer
from kivy_garden.mapview.source import MapSource

# Android permission handling
try:
    from android.permissions import request_permissions, Permission, check_permission
    ANDROID_PLATFORM = True
except ImportError:
    ANDROID_PLATFORM = False

try:
    from plyer import gps, notification
except ImportError:
    gps = None
    notification = None

# --- Theme Palette ---
THEMES = {
    'dark': {
        'bg': (0.05, 0.07, 0.10, 1),
        'card': (0.11, 0.14, 0.19, 0.95),
        'card_border': (0.18, 0.22, 0.30, 1),
        'text_primary': (0.95, 0.96, 0.98, 1),
        'text_secondary': (0.55, 0.60, 0.70, 1),
        'accent': (0.2, 0.5, 1.0, 1),
        'accent_green': (0.1, 0.8, 0.5, 1),
        'danger': (0.95, 0.3, 0.3, 1),
        'warning': (0.98, 0.6, 0.2, 1),
        'map_attribution': (0.8, 0.8, 0.8, 0.8),
    },
    'light': {
        'bg': (0.95, 0.96, 0.98, 1),
        'card': (1, 1, 1, 0.95),
        'card_border': (0.88, 0.90, 0.94, 1),
        'text_primary': (0.08, 0.12, 0.20, 1),
        'text_secondary': (0.50, 0.55, 0.65, 1),
        'accent': (0.14, 0.44, 0.98, 1),
        'accent_green': (0.08, 0.72, 0.44, 1),
        'danger': (0.90, 0.20, 0.20, 1),
        'warning': (0.95, 0.55, 0.10, 1),
        'map_attribution': (0.3, 0.3, 0.3, 0.8),
    }
}

DB_NAME = "travel_assistant_v10.db"
DEFAULT_LANDMARKS = [
    ("Clock Tower Landmark", 10.5380, 76.2250, "custom"),
    ("Public Library Plaza", 10.5230, 76.2160, "custom"),
]

# --- Offline tile cache ---
OSM_TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
OSM_USER_AGENT = "TravelAssistantApp/2.0"

def get_app_storage_dir():
    app = App.get_running_app()
    return app.user_data_dir if app else "."

def get_map_cache_dir():
    path = os.path.join(get_app_storage_dir(), "map_tiles")
    os.makedirs(path, exist_ok=True)
    return path

def build_osm_map_source(cache_dir):
    return MapSource(
        url=OSM_TILE_URL,
        cache_key="osm",
        min_zoom=0,
        max_zoom=19,
        attribution="© OpenStreetMap",
        cache_dir=cache_dir,
    )

def lonlat_to_tile(lat, lon, zoom):
    lat_rad = math.radians(lat)
    n = 2.0 ** zoom
    xtile = int((lon + 180.0) / 360.0 * n)
    ytile = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return xtile, ytile

def prefetch_area(lat, lon, zooms, radius, cache_dir, cache_key="osm",
                   progress_cb=None, done_cb=None):
    os.makedirs(cache_dir, exist_ok=True)
    jobs = []
    seen = set()
    for z in zooms:
        z = int(z)
        cx, cy = lonlat_to_tile(lat, lon, z)
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                key = (z, cx + dx, cy + dy)
                if key not in seen:
                    seen.add(key)
                    jobs.append(key)
    total = len(jobs) or 1

    def worker():
        done = 0
        for z, x, y in jobs:
            fn = os.path.join(cache_dir, f"{cache_key}_{z}_{x}_{y}.png")
            if not os.path.exists(fn):
                try:
                    req = urllib.request.Request(
                        OSM_TILE_URL.format(z=z, x=x, y=y),
                        headers={"User-Agent": OSM_USER_AGENT})
                    with urllib.request.urlopen(req, timeout=6) as resp:
                        data = resp.read()
                    tmp = fn + ".tmp"
                    with open(tmp, "wb") as f:
                        f.write(data)
                    os.replace(tmp, fn)
                except Exception:
                    pass
                time.sleep(0.15)
            done += 1
            if progress_cb:
                _call_on_main(progress_cb, done, total)
        if done_cb:
            _call_on_main(done_cb)

    threading.Thread(target=worker, daemon=True).start()

def clear_tile_cache(cache_dir):
    removed = 0
    try:
        for fn in os.listdir(cache_dir):
            fp = os.path.join(cache_dir, fn)
            if os.path.isfile(fp):
                os.remove(fp)
                removed += 1
    except Exception:
        pass
    return removed

@mainthread
def _call_on_main(cb, *args):
    cb(*args)

# --- Routing helpers ---
def decode_polyline(polyline_str):
    if not polyline_str:
        return []
    index, lat, lng = 0, 0, 0
    coordinates = []
    length = len(polyline_str)
    while index < length:
        byte, result, shift = 0, 0, 0
        while True:
            byte = ord(polyline_str[index]) - 63
            index += 1
            result |= (byte & 0x1f) << shift
            shift += 5
            if byte < 0x20:
                break
        dlat = ~(result >> 1) if (result & 1) else (result >> 1)
        lat += dlat
        shift, result = 0, 0
        while True:
            byte = ord(polyline_str[index]) - 63
            index += 1
            result |= (byte & 0x1f) << shift
            shift += 5
            if byte < 0x20:
                break
        dlng = ~(result >> 1) if (result & 1) else (result >> 1)
        lng += dlng
        coordinates.append((lat / 1e5, lng / 1e5))
    return coordinates

def get_db():
    db_path = os.path.join(get_app_storage_dir(), DB_NAME)
    return sqlite3.connect(db_path, timeout=10.0, check_same_thread=False)

def init_db():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS places (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                lat REAL NOT NULL,
                lon REAL NOT NULL,
                distance_km REAL,
                duration_mins INTEGER,
                last_updated TEXT,
                category TEXT DEFAULT 'custom'
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS origin (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                lat REAL NOT NULL,
                lon REAL NOT NULL,
                name TEXT NOT NULL
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS route_cache (
                route_hash TEXT PRIMARY KEY,
                distance_km REAL,
                duration_mins INTEGER,
                geometry TEXT,
                cached_at TEXT
            )
        ''')
        cursor.execute('''
            INSERT OR IGNORE INTO origin (id, lat, lon, name)
            VALUES (1, 10.5276, 76.2144, 'Current Location')
        ''')
        cursor.execute("SELECT COUNT(*) FROM places")
        if cursor.fetchone()[0] == 0:
            now_str = datetime.datetime.now().strftime("%b %d, %H:%M")
            for name, lat, lon, cat in DEFAULT_LANDMARKS:
                cursor.execute('''
                    INSERT INTO places (name, lat, lon, distance_km, duration_mins, last_updated, category)
                    VALUES (?, ?, ?, 0.0, 0, ?, ?)
                ''', (name, lat, lon, now_str, cat))

def get_route_cache(u_lat, u_lon, t_lat, t_lon):
    key = hashlib.md5(f"{u_lat:.4f},{u_lon:.4f}->{t_lat:.4f},{t_lon:.4f}".encode()).hexdigest()
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT distance_km, duration_mins, geometry FROM route_cache WHERE route_hash = ?", (key,))
            return cursor.fetchone()
    except Exception:
        return None

def set_route_cache(u_lat, u_lon, t_lat, t_lon, dist, dur, geom):
    key = hashlib.md5(f"{u_lat:.4f},{u_lon:.4f}->{t_lat:.4f},{t_lon:.4f}".encode()).hexdigest()
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO route_cache (route_hash, distance_km, duration_mins, geometry, cached_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (key, dist, dur, geom, now_str))
    except Exception:
        pass

def save_place_to_db(name, lat, lon, distance_km, duration_mins, last_updated, category="custom"):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO places (name, lat, lon, distance_km, duration_mins, last_updated, category)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (name, lat, lon, distance_km, duration_mins, last_updated, category))

def delete_place(place_id):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM places WHERE id = ?", (place_id,))

def get_all_places(category_filter=None):
    with get_db() as conn:
        cursor = conn.cursor()
        if category_filter:
            cursor.execute("SELECT id, name, lat, lon, distance_km, duration_mins, last_updated, category FROM places WHERE category = ? ORDER BY id DESC", (category_filter,))
        else:
            cursor.execute("SELECT id, name, lat, lon, distance_km, duration_mins, last_updated, category FROM places ORDER BY id DESC")
        return cursor.fetchall()

def set_origin_location(lat, lon, label="Custom Origin"):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE origin SET lat = ?, lon = ?, name = ? WHERE id = 1", (lat, lon, label))

def get_origin_location():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT lat, lon, name FROM origin WHERE id = 1")
        row = cursor.fetchone()
        return row if row else (10.5276, 76.2144, "Default Location")

def auto_detect_location(callback=None):
    def on_success(req, result):
        if callback:
            try:
                lat = float(result.get("latitude", 10.5276))
                lon = float(result.get("longitude", 76.2144))
                callback(lat, lon)
            except Exception:
                callback(10.5276, 76.2144)
    def on_error(req, error):
        if callback:
            callback(10.5276, 76.2144)
    UrlRequest("https://ipapi.co/json/", on_success=on_success, on_failure=on_error, on_error=on_error, timeout=4.0)

def locate_once(callback, timeout=30.0):
    """Get device position with high accuracy. Fallback to IP after timeout."""
    if not gps:
        auto_detect_location(callback)
        return

    state = {"done": False}
    def finish(lat, lon):
        if state["done"]:
            return
        state["done"] = True
        try: gps.stop()
        except: pass
        callback(lat, lon)

    def on_location(**kwargs):
        lat = kwargs.get('lat')
        lon = kwargs.get('lon')
        if lat and lon:
            finish(lat, lon)

    def on_timeout(dt):
        if not state["done"]:
            state["done"] = True
            try: gps.stop()
            except: pass
            auto_detect_location(callback)

    try:
        gps.configure(on_location=on_location, on_status=lambda *a,**k: None)
        gps.start(minTime=1000, minDistance=1)
        Clock.schedule_once(on_timeout, timeout)
    except Exception:
        auto_detect_location(callback)

def fetch_route_info_async(user_lat, user_lon, target_lat, target_lon, callback):
    timestamp = datetime.datetime.now().strftime("%b %d, %H:%M")
    cached = get_route_cache(user_lat, user_lon, target_lat, target_lon)
    if cached:
        dist_km, dur_mins, geom = cached
        coords = decode_polyline(geom) if geom else []
        callback(dist_km, dur_mins, f"Cached ({timestamp})", coords)
        return
    def fallback(*args):
        R = 6371.0
        dlat = math.radians(target_lat - user_lat)
        dlon = math.radians(target_lon - user_lon)
        a = math.sin(dlat/2)**2 + math.cos(math.radians(user_lat))*math.cos(math.radians(target_lat))*math.sin(dlon/2)**2
        c = 2*math.atan2(math.sqrt(a), math.sqrt(1-a))
        dist_km = round(R*c,2)
        est_mins = int((dist_km/40.0)*60)
        callback(dist_km, est_mins, f"Est. ({timestamp})", [])
    def on_success(req, data):
        try:
            if "routes" in data and len(data["routes"])>0:
                route = data["routes"][0]
                dist_km = round(route["distance"]/1000.0,2)
                dur_mins = int(route["duration"]/60.0)
                geometry = route.get("geometry","")
                set_route_cache(user_lat, user_lon, target_lat, target_lon, dist_km, dur_mins, geometry)
                coords = decode_polyline(geometry) if geometry else []
                callback(dist_km, dur_mins, f"Live ({timestamp})", coords)
            else:
                fallback()
        except Exception:
            fallback()
    url = f"https://router.project-osrm.org/route/v1/driving/{user_lon},{user_lat};{target_lon},{target_lat}?overview=full"
    UrlRequest(url, on_success=on_success, on_failure=fallback, on_error=fallback, timeout=4.0)

def calculate_bearing_and_cardinal(lat1, lon1, lat2, lon2):
    d_lon = math.radians(lon2 - lon1)
    y = math.sin(d_lon) * math.cos(math.radians(lat2))
    x = math.cos(math.radians(lat1)) * math.sin(math.radians(lat2)) - math.sin(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.cos(d_lon)
    bearing = (math.degrees(math.atan2(y, x)) + 360) % 360
    dirs = ["N","NE","E","SE","S","SW","W","NW"]
    idx = int((bearing + 22.5)//45) % 8
    return bearing, dirs[idx]

# --- Map overlay layers ---
class RouteLayer(MapLayer):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.coords = []
        with self.canvas:
            self._outline_color = Color(0.05, 0.22, 0.55, 0.55)
            self._outline = Line(width=dp(7), cap='round', joint='round')
            self._color = Color(0.16, 0.48, 0.98, 0.95)
            self._line = Line(width=dp(5), cap='round', joint='round')
    def set_coords(self, coords, is_estimate=False):
        self.coords = coords or []
        dash_len = dp(10) if is_estimate else 1
        dash_off = dp(6) if is_estimate else 0
        self._line.dash_length = dash_len
        self._line.dash_offset = dash_off
        self._outline.dash_length = dash_len
        self._outline.dash_offset = dash_off
        self.reposition()
    def reposition(self):
        if not self.coords or self.parent is None:
            self._line.points = []
            self._outline.points = []
            return
        mapview = self.parent
        pts = []
        for lat, lon in self.coords:
            x, y = mapview.get_window_xy_from(lat, lon, mapview.zoom)
            pts.extend((x, y))
        self._line.points = pts
        self._outline.points = pts

class UserDotLayer(MapLayer):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.user_lat = None
        self.user_lon = None
        with self.canvas:
            self._halo_color = Color(0.14, 0.44, 0.98, 0.25)
            self._halo = Ellipse(size=(dp(44), dp(44)))
            self._dot_color = Color(0.14, 0.44, 0.98, 1)
            self._dot = Ellipse(size=(dp(20), dp(20)))
            self._core_color = Color(1, 1, 1, 1)
            self._core = Ellipse(size=(dp(8), dp(8)))
    def set_position(self, lat, lon):
        self.user_lat = lat
        self.user_lon = lon
        self.reposition()
    def reposition(self):
        if self.user_lat is None or self.parent is None:
            return
        mapview = self.parent
        x, y = mapview.get_window_xy_from(self.user_lat, self.user_lon, mapview.zoom)
        self._halo.pos = (x - dp(22), y - dp(22))
        self._dot.pos = (x - dp(10), y - dp(10))
        self._core.pos = (x - dp(4), y - dp(4))

# --- UI Controls ---
class SmoothButton(Button):
    def __init__(self, bg_color=(0.14, 0.44, 0.98, 1), radius=16, **kwargs):
        super().__init__(**kwargs)
        self.background_normal = ''
        self.background_color = (0,0,0,0)
        self.custom_bg = bg_color
        self.radius = radius
        with self.canvas.before:
            self.color_inst = Color(*self.custom_bg)
            self.rect = RoundedRectangle(size=self.size, pos=self.pos, radius=[dp(self.radius)])
        self.bind(size=self._update_rect, pos=self._update_rect)
    def update_color(self, new_color):
        self.custom_bg = new_color
        self.color_inst.rgba = new_color
    def _update_rect(self, instance, value):
        self.rect.size = instance.size
        self.rect.pos = instance.pos

class SmoothTextInput(TextInput):
    def __init__(self, radius=16, **kwargs):
        super().__init__(**kwargs)
        self.background_normal = ''
        self.background_active = ''
        self.background_color = (0,0,0,0)
        with self.canvas.before:
            self.bg_color = Color(1,1,1,1)
            self.rect = RoundedRectangle(size=self.size, pos=self.pos, radius=[dp(radius)])
            self.border_color = Color(0.85,0.88,0.92,1)
            self.border_line = Line(rounded_rectangle=(self.pos[0],self.pos[1],self.size[0],self.size[1],dp(radius)), width=dp(1))
        self.bind(size=self._update_rect, pos=self._update_rect)
    def update_style(self, bg_rgba, border_rgba):
        self.bg_color.rgba = bg_rgba
        self.border_color.rgba = border_rgba
    def _update_rect(self, instance, value):
        self.rect.size = instance.size
        self.rect.pos = instance.pos
        self.border_line.rounded_rectangle = (instance.pos[0],instance.pos[1],instance.size[0],instance.size[1],dp(16))

class CustomSwitch(ButtonBehavior, Widget):
    def __init__(self, active=True, callback=None, **kwargs):
        super().__init__(**kwargs)
        self.size_hint = (None, None)
        self.size = (dp(50), dp(28))
        self.active = active
        self.callback = callback
        with self.canvas:
            self.track_color = Color()
            self.track = RoundedRectangle(size=self.size, pos=self.pos, radius=[dp(14)])
            self.thumb_color = Color(1,1,1,1)
            self.thumb = RoundedRectangle(size=(dp(22), dp(22)), radius=[dp(11)])
        self.bind(pos=self._update_graphics, size=self._update_graphics)
        self._update_graphics()
    def _update_graphics(self, *args):
        self.track.pos = self.pos
        self.track.size = self.size
        if self.active:
            self.track_color.rgba = (0.2, 0.5, 1.0, 1)
            self.thumb.pos = (self.pos[0] + self.width - dp(25), self.pos[1] + dp(3))
        else:
            self.track_color.rgba = (0.35, 0.38, 0.45, 1)
            self.thumb.pos = (self.pos[0] + dp(3), self.pos[1] + dp(3))
    def on_release(self):
        self.active = not self.active
        self._update_graphics()
        if self.callback:
            self.callback(self, self.active)

class DynamicScreen(Screen):
    def apply_theme(self, mode):
        pass

# --- Home Screen ---
class HomeScreen(DynamicScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.current_filter = None
        self.main_layout = BoxLayout(orientation='vertical', padding=dp(18), spacing=dp(12))
        with self.main_layout.canvas.before:
            self.bg_color_inst = Color(0.95,0.96,0.98,1)
            self.bg_rect = RoundedRectangle(size=self.main_layout.size, pos=self.main_layout.pos)
        self.main_layout.bind(size=self._update_bg, pos=self._update_bg)
        header = BoxLayout(size_hint_y=None, height=dp(64), spacing=dp(10))
        title_box = BoxLayout(orientation='vertical', spacing=dp(2))
        self.main_title = Label(text="[b]Travel Assistant[/b]", markup=True, font_size=sp(22), halign='left')
        self.origin_label = Label(text="Origin: Fetching...", font_size=sp(12), halign='left')
        title_box.add_widget(self.main_title)
        title_box.add_widget(self.origin_label)
        header.add_widget(title_box)
        btn_box = BoxLayout(size_hint_x=0.72, spacing=dp(8))   # accommodate 3 buttons
        self.settings_btn = SmoothButton(text=" ⚙️ ", size_hint_x=0.22, font_size=sp(20), radius=16)
        self.settings_btn.bind(on_release=lambda x: setattr(self.manager, 'current', 'settings'))
        btn_box.add_widget(self.settings_btn)
        self.download_btn = SmoothButton(text=" 📥 ", size_hint_x=0.22, font_size=sp(18), radius=16)
        self.download_btn.bind(on_release=lambda x: setattr(self.manager, 'current', 'download'))
        btn_box.add_widget(self.download_btn)
        self.add_btn = SmoothButton(text="+ Add", size_hint_x=0.56, bold=True, font_size=sp(12), radius=16)
        self.add_btn.bind(on_release=lambda x: setattr(self.manager, 'current', 'add_place'))
        btn_box.add_widget(self.add_btn)
        header.add_widget(btn_box)
        self.main_layout.add_widget(header)
        filter_bar = BoxLayout(size_hint_y=None, height=dp(36), spacing=dp(8))
        self.btn_filter_all = SmoothButton(text="All Places", font_size=sp(12), radius=10)
        self.btn_filter_all.bind(on_release=lambda x: self.set_filter(None))
        self.btn_filter_saved = SmoothButton(text="Saved Custom", font_size=sp(12), radius=10)
        self.btn_filter_saved.bind(on_release=lambda x: self.set_filter("custom"))
        filter_bar.add_widget(self.btn_filter_all)
        filter_bar.add_widget(self.btn_filter_saved)
        self.main_layout.add_widget(filter_bar)
        scroll = ScrollView(bar_width=dp(4), scroll_type=['content'])
        self.list_layout = BoxLayout(orientation='vertical', size_hint_y=None, spacing=dp(12))
        self.list_layout.bind(minimum_height=self.list_layout.setter('height'))
        scroll.add_widget(self.list_layout)
        self.main_layout.add_widget(scroll)
        self.add_widget(self.main_layout)

    def _update_bg(self, instance, value):
        self.bg_rect.size = instance.size
        self.bg_rect.pos = instance.pos

    def set_filter(self, category):
        self.current_filter = category
        self.refresh_list()

    def apply_theme(self, mode):
        t = THEMES[mode]
        self.bg_color_inst.rgba = t['bg']
        self.main_title.color = t['text_primary']
        self.origin_label.color = t['accent_green']
        self.settings_btn.update_color(t['card_border'])
        self.settings_btn.color = t['text_primary']
        self.download_btn.update_color(t['card_border'])
        self.download_btn.color = t['text_primary']
        self.add_btn.update_color(t['accent'])
        self.refresh_list()

    def on_enter(self):
        app = App.get_running_app()
        self.apply_theme(app.current_theme)
        o_lat, o_lon, o_name = get_origin_location()
        self.origin_label.text = f"Origin: {o_name} ({o_lat:.2f}, {o_lon:.2f})"
        self.refresh_list()

    def refresh_list(self):
        self.list_layout.clear_widgets()
        app = App.get_running_app()
        t = THEMES[app.current_theme]
        places = get_all_places(category_filter=self.current_filter)
        if not places:
            lbl = Label(text="No places found.", size_hint_y=None, height=dp(120), color=t['text_secondary'], font_size=sp(14))
            self.list_layout.add_widget(lbl)
            return
        for p_id, name, lat, lon, dist_km, duration_mins, last_updated, category in places:
            tag = "[SAVED PLACE]"
            card = BoxLayout(orientation='vertical', size_hint_y=None, height=dp(130), padding=dp(12), spacing=dp(4))
            with card.canvas.before:
                Color(*t['card'])
                rect = RoundedRectangle(size=card.size, pos=card.pos, radius=[dp(16)])
                Color(*t['card_border'])
                border = Line(rounded_rectangle=(card.pos[0],card.pos[1],card.size[0],card.size[1],dp(16)), width=dp(1))
            def sync_card(instance, value, r=rect, b=border):
                r.size = instance.size; r.pos = instance.pos
                b.rounded_rectangle = (instance.pos[0],instance.pos[1],instance.size[0],instance.size[1],dp(16))
            card.bind(size=sync_card, pos=sync_card)
            t_label = Label(text=f"[b]{tag} {name}[/b]", markup=True, halign='left', font_size=sp(14), color=t['text_primary'])
            s_label = Label(text=f"Coords: {lat:.4f}, {lon:.4f} | {last_updated}", color=t['text_secondary'], halign='left', font_size=sp(11))
            card.add_widget(t_label)
            card.add_widget(s_label)
            actions = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(8))
            nav_btn = SmoothButton(text="Navigate Here", bg_color=t['accent'], font_size=sp(12), bold=True, radius=12)
            nav_btn.bind(on_release=lambda inst, nm=name, lt=lat, ln=lon: self.start_inapp_nav(nm, lt, ln))
            actions.add_widget(nav_btn)
            del_btn = SmoothButton(text="Delete", size_hint_x=0.28, bg_color=t['danger'], font_size=sp(12), radius=12)
            del_btn.bind(on_release=lambda inst, pid=p_id: self.delete_entry(pid))
            actions.add_widget(del_btn)
            card.add_widget(actions)
            self.list_layout.add_widget(card)

    def start_inapp_nav(self, name, dest_lat, dest_lon):
        nav_screen = self.manager.get_screen('navigation')
        nav_screen.setup_route(name, dest_lat, dest_lon)
        self.manager.current = 'navigation'

    def delete_entry(self, place_id):
        delete_place(place_id)
        self.refresh_list()

# --- Add Place Screen (unchanged, keep as is from your script) ---
class AddPlaceScreen(DynamicScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.place_markers = []
        self.search_suggestions = []

        main_layout = FloatLayout()

        cache_dir = get_map_cache_dir()
        self.map_view = MapView(zoom=16, lat=10.5276, lon=76.2144)
        self.map_view.cache_dir = cache_dir
        self.map_view.map_source = build_osm_map_source(cache_dir)
        main_layout.add_widget(self.map_view)

        # Center pin (fixed)
        self.center_pin = Widget(size_hint=(None,None), size=(dp(30),dp(40)), pos_hint={'center_x':0.5,'center_y':0.5})
        with self.center_pin.canvas:
            Color(0,0,0,0.35); self._pin_shadow = Ellipse(size=(dp(16),dp(7)))
            Color(0.95,0.25,0.25,1); self._pin_head = Ellipse(size=(dp(26),dp(26)))
            Color(1,1,1,1); self._pin_core = Ellipse(size=(dp(10),dp(10)))
        self.center_pin.bind(pos=self._sync_pin, size=self._sync_pin)
        main_layout.add_widget(self.center_pin)

        # Top card with search
        self.top_card = BoxLayout(orientation='vertical', size_hint=(0.92,None), height=dp(150), pos_hint={'center_x':0.5,'top':0.97}, padding=dp(10), spacing=dp(6))
        with self.top_card.canvas.before:
            self.tc_bg = Color(1,1,1,0.95)
            self.tc_rect = RoundedRectangle(size=self.top_card.size, pos=self.top_card.pos, radius=[dp(18)])
        self.top_card.bind(size=self._sync_tc, pos=self._sync_tc)

        search_box = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(6))
        self.search_input = SmoothTextInput(hint_text="Search for a place...", multiline=False, font_size=sp(13))
        search_btn = SmoothButton(text="🔍", size_hint_x=0.2, font_size=sp(18))
        search_btn.bind(on_release=self.do_search)
        search_box.add_widget(self.search_input)
        search_box.add_widget(search_btn)
        self.top_card.add_widget(search_box)

        self.suggestions_box = BoxLayout(orientation='vertical', size_hint_y=None, height=dp(80), spacing=dp(2))
        scroll_sugg = ScrollView(bar_width=dp(4), size_hint=(1,1))
        scroll_sugg.add_widget(self.suggestions_box)
        self.top_card.add_widget(scroll_sugg)

        self.status_label = Label(text="Drag the map - the pin marks the spot", size_hint_y=None, height=dp(22), font_size=sp(11), bold=True)
        self.top_card.add_widget(self.status_label)
        main_layout.add_widget(self.top_card)

        dock = BoxLayout(orientation='vertical', size_hint=(0.92,None), height=dp(170), pos_hint={'center_x':0.5,'y':0.02}, spacing=dp(8))
        row1 = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(8))
        self.locate_btn = SmoothButton(text="📍 Locate Me", font_size=sp(12), bold=True, radius=14)
        self.locate_btn.bind(on_release=self.locate_me)
        row1.add_widget(self.locate_btn)
        dock.add_widget(row1)
        row_offline = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(8))
        self.offline_btn = SmoothButton(text="Download Offline Area", font_size=sp(12), bold=True, radius=14)
        self.offline_btn.bind(on_release=self.download_offline_area)
        row_offline.add_widget(self.offline_btn)
        dock.add_widget(row_offline)
        row2 = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
        self.back_btn = SmoothButton(text="Back", size_hint_x=0.35, font_size=sp(13), radius=16)
        self.back_btn.bind(on_release=lambda x: setattr(self.manager, 'current', 'home'))
        row2.add_widget(self.back_btn)
        self.save_btn = SmoothButton(text="Save Place", size_hint_x=0.65, bold=True, font_size=sp(13), radius=16)
        self.save_btn.bind(on_release=self.save_data)
        row2.add_widget(self.save_btn)
        dock.add_widget(row2)
        main_layout.add_widget(dock)

        self.add_widget(main_layout)

    def _sync_pin(self, instance, value):
        cx, cy = instance.center_x, instance.center_y
        self._pin_shadow.pos = (cx - dp(8), instance.y - dp(1))
        self._pin_head.pos = (cx - dp(13), cy - dp(6))
        self._pin_core.pos = (cx - dp(5), cy + dp(2))

    def _sync_tc(self, instance, value):
        self.tc_rect.size = instance.size
        self.tc_rect.pos = instance.pos

    def do_search(self, instance):
        query = self.search_input.text.strip()
        if not query:
            return
        url = f"https://nominatim.openstreetmap.org/search?q={urllib.parse.quote(query)}&format=json&limit=5"
        def on_success(req, result):
            try:
                data = json.loads(result) if isinstance(result, str) else result
                self.suggestions_box.clear_widgets()
                self.search_suggestions = []
                if not data:
                    self.suggestions_box.add_widget(Label(text="No results", font_size=sp(12)))
                    return
                for place in data[:5]:
                    lat = float(place['lat'])
                    lon = float(place['lon'])
                    name = place['display_name']
                    self.search_suggestions.append((name, lat, lon))
                    btn = SmoothButton(text=name[:60], size_hint_y=None, height=dp(30), font_size=sp(11), halign='left')
                    btn.bind(on_release=lambda btn, lat=lat, lon=lon, nm=name: self.select_suggestion(lat, lon, nm))
                    self.suggestions_box.add_widget(btn)
            except Exception as e:
                self.suggestions_box.clear_widgets()
                self.suggestions_box.add_widget(Label(text="Search failed", font_size=sp(12)))
        def on_error(req, error):
            self.suggestions_box.clear_widgets()
            self.suggestions_box.add_widget(Label(text="Network error", font_size=sp(12)))
        UrlRequest(url, on_success=on_success, on_failure=on_error, on_error=on_error)

    def select_suggestion(self, lat, lon, name):
        self.map_view.center_on(lat, lon)
        self.search_input.text = name
        self.suggestions_box.clear_widgets()

    def apply_theme(self, mode):
        t = THEMES[mode]
        self.tc_bg.rgba = t['card']
        self.search_input.foreground_color = t['text_primary']
        self.search_input.hint_text_color = t['text_secondary']
        self.search_input.update_style(t['bg'], t['card_border'])
        self.status_label.color = t['accent']
        self.locate_btn.update_color(t['warning'])
        self.offline_btn.update_color(t['card_border'])
        self.offline_btn.color = t['text_primary']
        self.back_btn.update_color(t['card_border'])
        self.back_btn.color = t['text_primary']
        self.save_btn.update_color(t['accent_green'])

    def on_enter(self):
        app = App.get_running_app()
        self.apply_theme(app.current_theme)
        o_lat, o_lon, _ = get_origin_location()
        self.map_view.center_on(o_lat, o_lon)
        for m in self.place_markers:
            self.map_view.remove_marker(m)
        self.place_markers = []
        for _, name, lat, lon, _, _, _, cat in get_all_places():
            marker = MapMarker(lat=lat, lon=lon, color=(0.1,0.8,0.5,1))
            marker.bind(on_release=lambda inst, nm=name: self._show_marker_name(nm))
            self.map_view.add_marker(marker)
            self.place_markers.append(marker)

    def _show_marker_name(self, name):
        self.status_label.text = f"📌 {name}"

    def locate_me(self, instance):
        self.locate_btn.text = "Locating..."
        self.locate_btn.disabled = True
        self.status_label.text = "Finding your location..."
        def on_located(lat, lon):
            self.locate_btn.text = "📍 Locate Me"
            self.locate_btn.disabled = False
            self.map_view.center_on(lat, lon)
            self.status_label.text = "You're here - tap Save Place to add it"
        locate_once(on_located)

    def download_offline_area(self, instance):
        lat, lon = self.map_view.lat, self.map_view.lon
        cache_dir = get_map_cache_dir()
        zoom = int(self.map_view.zoom)
        zooms = sorted(set([max(0,zoom-1), zoom, min(19,zoom+1)]))
        self.offline_btn.text = "Downloading..."
        self.offline_btn.disabled = True
        def progress(done, total):
            self.status_label.text = f"Caching tiles: {done}/{total}"
        def finished():
            self.offline_btn.text = "Download Offline Area"
            self.offline_btn.disabled = False
            self.status_label.text = "Area cached - viewable offline now"
        prefetch_area(lat, lon, zooms, radius=2, cache_dir=cache_dir,
                       progress_cb=progress, done_cb=finished)

    def save_data(self, instance):
        target_lat, target_lon = self.map_view.lat, self.map_view.lon
        name = self.search_input.text.strip() or f"Spot ({target_lat:.2f}, {target_lon:.2f})"
        o_lat, o_lon, _ = get_origin_location()
        def on_route_done(dist_km, dur_mins, sync_time, coords):
            save_place_to_db(name, target_lat, target_lon, dist_km, dur_mins, sync_time, category="custom")
            self.search_input.text = ""
            self.suggestions_box.clear_widgets()
            self.manager.current = "home"
        fetch_route_info_async(o_lat, o_lon, target_lat, target_lon, on_route_done)

# --- Navigation Screen (unchanged) ---
class NavigationScreen(DynamicScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.dest_lat = None
        self.dest_lon = None
        self.dest_name = ""
        self.dest_marker = None
        self.current_lat = 0.0
        self.current_lon = 0.0
        self._last_recalc_time = 0.0
        self._last_recalc_pos = None
        self.mosque_markers = []
        self.prayer_times = {}

        main_layout = FloatLayout()

        cache_dir = get_map_cache_dir()
        self.map_view = MapView(zoom=16, lat=10.5276, lon=76.2144, rotation=0)
        self.map_view.cache_dir = cache_dir
        self.map_view.map_source = build_osm_map_source(cache_dir)
        main_layout.add_widget(self.map_view)

        self.route_layer = RouteLayer()
        self.map_view.add_layer(self.route_layer)

        self.user_layer = UserDotLayer()
        self.map_view.add_layer(self.user_layer)

        # Top info card
        self.top_card = BoxLayout(orientation='vertical', size_hint=(0.92,None), height=dp(85), pos_hint={'center_x':0.5,'top':0.97}, padding=dp(12), spacing=dp(4))
        with self.top_card.canvas.before:
            self.tc_bg = Color(0.08,0.12,0.2,0.96)
            self.tc_rect = RoundedRectangle(size=self.top_card.size, pos=self.top_card.pos, radius=[dp(18)])
        self.top_card.bind(size=self._sync_tc, pos=self._sync_tc)
        self.dest_name_lbl = Label(text="Navigating...", bold=True, font_size=sp(15), color=(1,1,1,1), halign='left')
        self.metrics_lbl = Label(text="Calculating route...", font_size=sp(12), color=(0.2,0.8,0.5,1), halign='left')
        self.top_card.add_widget(self.dest_name_lbl)
        self.top_card.add_widget(self.metrics_lbl)
        main_layout.add_widget(self.top_card)

        # Speed HUD
        self.hud_card = BoxLayout(orientation='vertical', size_hint=(None,None), size=(dp(85), dp(65)), pos_hint={'x':0.04, 'y':0.12}, padding=dp(6))
        with self.hud_card.canvas.before:
            Color(0.1,0.14,0.2,0.9)
            self.hud_rect = RoundedRectangle(size=self.hud_card.size, pos=self.hud_card.pos, radius=[dp(14)])
            Color(0.2,0.5,1.0,1)
            self.hud_border = Line(rounded_rectangle=(self.hud_card.pos[0],self.hud_card.pos[1],self.hud_card.size[0],self.hud_card.size[1],dp(14)), width=dp(1.2))
        self.hud_card.bind(size=self._sync_hud, pos=self._sync_hud)
        self.speed_val_lbl = Label(text="0", font_size=sp(20), bold=True, color=(0.1,0.8,0.5,1))
        self.speed_unit_lbl = Label(text="km/h", font_size=sp(10), color=(0.7,0.75,0.85,1))
        self.hud_card.add_widget(self.speed_val_lbl)
        self.hud_card.add_widget(self.speed_unit_lbl)
        main_layout.add_widget(self.hud_card)

        # Prayer time mini-card
        self.prayer_card = BoxLayout(orientation='vertical', size_hint=(None,None), size=(dp(120), dp(70)), pos_hint={'right':0.98, 'y':0.06}, padding=dp(6))
        with self.prayer_card.canvas.before:
            Color(0.05,0.1,0.2,0.9)
            self.prayer_rect = RoundedRectangle(size=self.prayer_card.size, pos=self.prayer_card.pos, radius=[dp(10)])
        self.prayer_card.bind(size=self._sync_prayer, pos=self._sync_prayer)
        self.prayer_title = Label(text="Prayer Times", font_size=sp(10), color=(0.9,0.9,0.9,1))
        self.prayer_times_lbl = Label(text="Loading...", font_size=sp(9), color=(0.8,0.8,0.8,1))
        self.prayer_card.add_widget(self.prayer_title)
        self.prayer_card.add_widget(self.prayer_times_lbl)
        main_layout.add_widget(self.prayer_card)

        # Recenter button
        recenter_btn = SmoothButton(text="📍", size_hint=(None,None), size=(dp(44),dp(44)), pos_hint={'right':0.98, 'y':0.18}, font_size=sp(20), radius=22)
        recenter_btn.bind(on_release=self.recenter_map)
        main_layout.add_widget(recenter_btn)

        # Compass button
        compass_btn = SmoothButton(text="🧭", size_hint=(None,None), size=(dp(40),dp(40)), pos_hint={'right':0.98, 'top':0.82}, font_size=sp(18), radius=20)
        compass_btn.bind(on_release=lambda x: setattr(self.map_view, 'rotation', 0))
        main_layout.add_widget(compass_btn)

        # Exit button
        dock = BoxLayout(size_hint=(0.92,None), height=dp(48), pos_hint={'center_x':0.5, 'y':0.03})
        exit_btn = SmoothButton(text="End Navigation", bg_color=(0.95,0.3,0.3,1), bold=True, font_size=sp(13), radius=18)
        exit_btn.bind(on_release=self.end_navigation)
        dock.add_widget(exit_btn)
        main_layout.add_widget(dock)

        self.add_widget(main_layout)

    def _sync_tc(self, instance, value):
        self.tc_rect.size = instance.size; self.tc_rect.pos = instance.pos
    def _sync_hud(self, instance, value):
        self.hud_rect.size = instance.size; self.hud_rect.pos = instance.pos
        self.hud_border.rounded_rectangle = (instance.pos[0],instance.pos[1],instance.size[0],instance.size[1],dp(14))
    def _sync_prayer(self, instance, value):
        self.prayer_rect.size = instance.size; self.prayer_rect.pos = instance.pos

    def recenter_map(self, instance):
        if self.current_lat and self.current_lon:
            self.map_view.center_on(self.current_lat, self.current_lon)

    def setup_route(self, dest_name, dest_lat, dest_lon):
        self.dest_name = dest_name
        self.dest_lat = dest_lat
        self.dest_lon = dest_lon
        self._last_recalc_time = 0.0
        self._last_recalc_pos = None
        o_lat, o_lon, _ = get_origin_location()
        self.current_lat = o_lat
        self.current_lon = o_lon
        if self.dest_marker:
            self.map_view.remove_marker(self.dest_marker)
        self.dest_marker = MapMarker(lat=dest_lat, lon=dest_lon, color=(0.95,0.3,0.3,1))
        self.map_view.add_marker(self.dest_marker)
        self.user_layer.set_position(self.current_lat, self.current_lon)
        self.map_view.zoom = 16
        self.map_view.center_on(self.current_lat, self.current_lon)
        self.speed_val_lbl.text = "--"
        self.speed_unit_lbl.text = "no signal"
        self.recalculate_route()
        self.start_gps_listening()
        # Start mosque & prayer time checks
        self._mosque_check_event = Clock.schedule_interval(self.fetch_nearby_mosques, 30)
        self._prayer_check_event = Clock.schedule_interval(self.fetch_prayer_times, 60)
        self.fetch_nearby_mosques()
        self.fetch_prayer_times()

    def recalculate_route(self):
        if self.dest_lat is None:
            return
        bearing, cardinal_str = calculate_bearing_and_cardinal(self.current_lat, self.current_lon, self.dest_lat, self.dest_lon)
        def on_route_calculated(dist_km, dur_mins, sync_str, polyline_coords):
            hours = dur_mins // 60
            mins = dur_mins % 60
            time_str = f"{hours}h {mins}m" if hours > 0 else f"{mins} mins"
            self.dest_name_lbl.text = f"Target: {self.dest_name}"
            self.metrics_lbl.text = f"Dist: {dist_km} km  •  ETA: {time_str} ({cardinal_str})"
            if polyline_coords:
                self.route_layer.set_coords(polyline_coords, is_estimate=False)
            else:
                self.route_layer.set_coords(
                    [(self.current_lat, self.current_lon), (self.dest_lat, self.dest_lon)],
                    is_estimate=True)
        fetch_route_info_async(self.current_lat, self.current_lon, self.dest_lat, self.dest_lon, on_route_calculated)

    def start_gps_listening(self):
        if not gps:
            self.speed_unit_lbl.text = "no gps"
            return
        try: gps.stop()
        except: pass
        try:
            gps.configure(on_location=self.on_gps_location, on_status=self.on_gps_status)
            gps.start(minTime=1000, minDistance=1)
        except Exception:
            self.speed_unit_lbl.text = "gps blocked"

    def on_gps_location(self, **kwargs):
        lat = kwargs.get('lat')
        lon = kwargs.get('lon')
        speed = kwargs.get('speed', None)
        if not lat or not lon:
            return
        self.current_lat = lat
        self.current_lon = lon
        self.user_layer.set_position(lat, lon)
        app = App.get_running_app()
        if app.touch_lock_enabled:
            self.map_view.center_on(lat, lon)
        if self.speed_unit_lbl.text != "km/h":
            self.speed_unit_lbl.text = "km/h"
        if speed is not None:
            kmh = max(0, speed * 3.6)
            self.speed_val_lbl.text = str(int(round(kmh)))
        else:
            self.speed_val_lbl.text = "0"
        self._maybe_recalculate_route(lat, lon)

    def _maybe_recalculate_route(self, lat, lon):
        now = time.time()
        moved_far = True
        if self._last_recalc_pos:
            plat, plon = self._last_recalc_pos
            moved_far = math.hypot(lat - plat, lon - plon) > 0.0008
        if moved_far and (now - self._last_recalc_time) > 15:
            self._last_recalc_time = now
            self._last_recalc_pos = (lat, lon)
            self.recalculate_route()

    def on_gps_status(self, *args, **kwargs):
        pass

    def fetch_nearby_mosques(self, *args):
        """Search for mosques within 5 km using Overpass API."""
        if not self.current_lat or not self.current_lon:
            return
        radius = 5000
        overpass_url = "https://overpass-api.de/api/interpreter"
        query = f"""
        [out:json];
        (
          node["amenity"="place_of_worship"]["religion"="muslim"](around:{radius},{self.current_lat},{self.current_lon});
          way["amenity"="place_of_worship"]["religion"="muslim"](around:{radius},{self.current_lat},{self.current_lon});
          relation["amenity"="place_of_worship"]["religion"="muslim"](around:{radius},{self.current_lat},{self.current_lon});
        );
        out center;
        """
        def on_success(req, result):
            try:
                data = json.loads(result) if isinstance(result, str) else result
                for m in self.mosque_markers:
                    self.map_view.remove_marker(m)
                self.mosque_markers = []
                for element in data.get('elements', []):
                    if element['type'] == 'node':
                        lat = element['lat']; lon = element['lon']
                    elif 'center' in element:
                        lat = element['center']['lat']; lon = element['center']['lon']
                    else:
                        continue
                    marker = MapMarker(lat=lat, lon=lon, color=(0.1, 0.9, 0.3, 1))
                    self.map_view.add_marker(marker)
                    self.mosque_markers.append(marker)
            except Exception as e:
                pass
        def on_error(req, error):
            pass
        UrlRequest(overpass_url, on_success=on_success, on_failure=on_error,
                   on_error=on_error, timeout=5.0,
                   req_body=urllib.parse.urlencode({'data': query}).encode(),
                   method='POST', req_headers={'Content-Type':'application/x-www-form-urlencoded'})

    def fetch_prayer_times(self, *args):
        """Get prayer times from Aladhan API."""
        if not self.current_lat or not self.current_lon:
            return
        today = datetime.date.today()
        month = today.month; year = today.year
        url = f"https://api.aladhan.com/v1/calendar?latitude={self.current_lat}&longitude={self.current_lon}&method=2&month={month}&year={year}"
        def on_success(req, result):
            try:
                data = json.loads(result) if isinstance(result, str) else result
                day = today.day
                times = data['data'][day-1]['timings']
                self.prayer_times = times
                now = datetime.datetime.now().strftime("%H:%M")
                next_prayer = None
                order = ['Fajr','Sunrise','Dhuhr','Asr','Maghrib','Isha']
                for p in order:
                    if times[p] > now:
                        next_prayer = p
                        break
                display = f"Next: {next_prayer or '---'} at {times.get(next_prayer,'--') if next_prayer else ''}"
                self.prayer_times_lbl.text = display
                self.check_and_notify_prayer()
            except Exception as e:
                self.prayer_times_lbl.text = "Prayer times error"
        def on_error(req, error):
            self.prayer_times_lbl.text = "Network error"
        UrlRequest(url, on_success=on_success, on_failure=on_error, on_error=on_error)

    def check_and_notify_prayer(self):
        if not notification:
            return
        now = datetime.datetime.now().strftime("%H:%M")
        app = App.get_running_app()
        if not app.prayer_notify_enabled:
            return
        for name, time_str in self.prayer_times.items():
            if time_str == now:
                notification.notify(
                    title="Prayer Time",
                    message=f"It's time for {name} prayer.",
                    app_name="Travel Assistant",
                    timeout=10
                )

    def end_navigation(self, instance):
        if gps:
            try: gps.stop()
            except: pass
        self.route_layer.set_coords([])
        for m in self.mosque_markers:
            self.map_view.remove_marker(m)
        self.mosque_markers = []
        if hasattr(self, '_mosque_check_event'):
            Clock.unschedule(self._mosque_check_event)
        if hasattr(self, '_prayer_check_event'):
            Clock.unschedule(self._prayer_check_event)
        self.dest_lat = None
        self.manager.current = 'home'

# --- Settings Screen (unchanged) ---
class SettingsScreen(DynamicScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.main_layout = BoxLayout(orientation='vertical', padding=dp(20), spacing=dp(18))
        with self.main_layout.canvas.before:
            self.bg_color_inst = Color(0.07,0.09,0.12,1)
            self.bg_rect = RoundedRectangle(size=self.main_layout.size, pos=self.main_layout.pos)
        self.main_layout.bind(size=self._update_bg, pos=self._update_bg)
        header = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(12))
        self.back_btn = SmoothButton(text="Back", size_hint_x=0.28, font_size=sp(14), radius=14)
        self.back_btn.bind(on_release=lambda x: setattr(self.manager, 'current', 'home'))
        header.add_widget(self.back_btn)
        self.title_lbl = Label(text="[b]Settings[/b]", markup=True, font_size=sp(22), halign='left')
        header.add_widget(self.title_lbl)
        self.main_layout.add_widget(header)
        self.card = BoxLayout(orientation='vertical', size_hint_y=None, height=dp(360), padding=[dp(18),dp(14)], spacing=dp(14))
        with self.card.canvas.before:
            self.card_bg = Color(0.13,0.16,0.22,0.95)
            self.card_rect = RoundedRectangle(size=self.card.size, pos=self.card.pos, radius=[dp(18)])
        self.card.bind(size=self._sync_card, pos=self._sync_card)
        row_dark = BoxLayout(size_hint_y=None, height=dp(40))
        self.dark_lbl = Label(text="Dark Theme", font_size=sp(14), halign='left')
        self.theme_switch = CustomSwitch(active=True, callback=self.toggle_theme)
        row_dark.add_widget(self.dark_lbl); row_dark.add_widget(self.theme_switch)
        self.card.add_widget(row_dark)
        row_lock = BoxLayout(size_hint_y=None, height=dp(40))
        self.lock_lbl = Label(text="Auto-Center Map", font_size=sp(13), halign='left')
        self.lock_switch = CustomSwitch(active=True, callback=self.toggle_touch_lock)
        row_lock.add_widget(self.lock_lbl); row_lock.add_widget(self.lock_switch)
        self.card.add_widget(row_lock)
        row_prayer = BoxLayout(size_hint_y=None, height=dp(40))
        self.prayer_lbl = Label(text="Prayer Notifications", font_size=sp(13), halign='left')
        self.prayer_switch = CustomSwitch(active=False, callback=self.toggle_prayer_notify)
        row_prayer.add_widget(self.prayer_lbl); row_prayer.add_widget(self.prayer_switch)
        self.card.add_widget(row_prayer)
        row_gps = BoxLayout(size_hint_y=None, height=dp(46))
        self.reset_gps_btn = SmoothButton(text="Reset Origin to Auto-GPS", font_size=sp(13), bold=True, radius=14)
        self.reset_gps_btn.bind(on_release=self.reset_gps)
        row_gps.add_widget(self.reset_gps_btn)
        self.card.add_widget(row_gps)
        row_cache = BoxLayout(size_hint_y=None, height=dp(46))
        self.clear_cache_btn = SmoothButton(text="Clear Offline Map Cache", font_size=sp(13), bold=True, radius=14)
        self.clear_cache_btn.bind(on_release=self.clear_map_cache)
        row_cache.add_widget(self.clear_cache_btn)
        self.card.add_widget(row_cache)
        self.main_layout.add_widget(self.card)
        self.main_layout.add_widget(Label())
        self.add_widget(self.main_layout)

    def _update_bg(self, instance, value):
        self.bg_rect.size = instance.size; self.bg_rect.pos = instance.pos
    def _sync_card(self, instance, value):
        self.card_rect.size = instance.size; self.card_rect.pos = instance.pos

    def apply_theme(self, mode):
        t = THEMES[mode]
        self.bg_color_inst.rgba = t['bg']
        self.card_bg.rgba = t['card']
        self.title_lbl.color = t['text_primary']
        self.dark_lbl.color = t['text_primary']
        self.lock_lbl.color = t['text_primary']
        self.prayer_lbl.color = t['text_primary']
        self.back_btn.update_color(t['card_border'])
        self.back_btn.color = t['text_primary']
        self.reset_gps_btn.update_color(t['accent'])
        self.clear_cache_btn.update_color(t['card_border'])
        self.clear_cache_btn.color = t['text_primary']

    def on_enter(self):
        app = App.get_running_app()
        self.theme_switch.active = (app.current_theme == 'dark')
        self.lock_switch.active = app.touch_lock_enabled
        self.prayer_switch.active = app.prayer_notify_enabled
        self.apply_theme(app.current_theme)

    def toggle_theme(self, instance, value):
        app = App.get_running_app()
        app.switch_theme('dark' if value else 'light')
    def toggle_touch_lock(self, instance, value):
        App.get_running_app().touch_lock_enabled = value
    def toggle_prayer_notify(self, instance, value):
        App.get_running_app().prayer_notify_enabled = value

    def reset_gps(self, instance):
        self.reset_gps_btn.text = "Locating..."
        def on_gps_reset(lat, lon):
            set_origin_location(lat, lon, "My Location")
            self.reset_gps_btn.text = "GPS Reset Successful!"
            Clock.schedule_once(lambda dt: setattr(self.reset_gps_btn, 'text', "Reset Origin to Auto-GPS"), 2.0)
        locate_once(on_gps_reset)

    def clear_map_cache(self, instance):
        removed = clear_tile_cache(get_map_cache_dir())
        self.clear_cache_btn.text = f"Cleared {removed} tiles"
        Clock.schedule_once(lambda dt: setattr(self.clear_cache_btn, 'text', "Clear Offline Map Cache"), 2.0)


# ============================================================
#            VIDEO DOWNLOADER WITH STORAGE LIMIT
# ============================================================
class DownloadScreen(DynamicScreen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.downloaded_path = None

        # Internal download folder
        self.download_dir = os.path.join(get_app_storage_dir(), "downloads")
        os.makedirs(self.download_dir, exist_ok=True)

        main_layout = FloatLayout()
        with main_layout.canvas.before:
            self.bg_color_inst = Color(*THEMES['dark']['bg'])
            self.bg_rect = RoundedRectangle(size=main_layout.size, pos=main_layout.pos)
        main_layout.bind(size=self._update_bg, pos=self._update_bg)

        card = BoxLayout(orientation='vertical', size_hint=(0.92, None), height=dp(380),
                         pos_hint={'center_x': 0.5, 'top': 0.92}, padding=dp(20), spacing=dp(12))
        with card.canvas.before:
            self.card_bg = Color(*THEMES['dark']['card'])
            self.card_rect = RoundedRectangle(size=card.size, pos=card.pos, radius=[dp(20)])
        card.bind(size=self._sync_card, pos=self._sync_card)

        # Title
        title = Label(text="[b]Video Downloader[/b]", markup=True, font_size=sp(20),
                      color=THEMES['dark']['text_primary'], size_hint_y=None, height=dp(36))
        card.add_widget(title)

        # Storage info
        self.storage_info_lbl = Label(text="Storage: 0 MB / 0 MB", font_size=sp(12),
                                      color=THEMES['dark']['text_secondary'], size_hint_y=None, height=dp(22))
        card.add_widget(self.storage_info_lbl)

        # Link input
        self.link_input = SmoothTextInput(hint_text="Paste video link here...", multiline=False,
                                          font_size=sp(14), size_hint_y=None, height=dp(48))
        card.add_widget(self.link_input)

        # Progress bar
        self.progress_bar = BoxLayout(size_hint_y=None, height=dp(16))
        with self.progress_bar.canvas:
            Color(0.2, 0.5, 1.0, 0.2)
            self.progress_bg = RoundedRectangle(size=self.progress_bar.size, pos=self.progress_bar.pos,
                                                radius=[dp(8)])
            self.progress_fill_color = Color(0.2, 0.5, 1.0, 1)
            self.progress_fill = RoundedRectangle(size=(0, dp(16)), pos=self.progress_bar.pos,
                                                  radius=[dp(8)])
        self.progress_bar.bind(size=self._update_progress_bar, pos=self._update_progress_bar)
        card.add_widget(self.progress_bar)

        # Status label
        self.status_lbl = Label(text="Enter a link and tap Download", font_size=sp(12),
                                color=THEMES['dark']['text_secondary'], size_hint_y=None, height=dp(24))
        card.add_widget(self.status_lbl)

        # Download button
        self.download_btn = SmoothButton(text="⬇ Download", bg_color=THEMES['dark']['accent'],
                                         bold=True, font_size=sp(15), radius=14, size_hint_y=None,
                                         height=dp(50))
        self.download_btn.bind(on_release=self.start_download)
        card.add_widget(self.download_btn)

        # Share button (hidden initially)
        self.share_btn = SmoothButton(text="📤 Share Video", bg_color=THEMES['dark']['accent_green'],
                                      bold=True, font_size=sp(15), radius=14, size_hint_y=None,
                                      height=dp(50))
        self.share_btn.bind(on_release=self.share_video)
        self.share_btn.opacity = 0
        self.share_btn.disabled = True
        card.add_widget(self.share_btn)

        main_layout.add_widget(card)

        # Back button
        back_btn = SmoothButton(text="← Back", size_hint=(None, None), size=(dp(100), dp(44)),
                                pos_hint={'x': 0.02, 'y': 0.03}, font_size=sp(14), radius=16)
        back_btn.bind(on_release=lambda x: setattr(self.manager, 'current', 'home'))
        main_layout.add_widget(back_btn)

        self.add_widget(main_layout)

    def _update_bg(self, instance, value):
        self.bg_rect.size = instance.size
        self.bg_rect.pos = instance.pos

    def _sync_card(self, instance, value):
        self.card_rect.size = instance.size
        self.card_rect.pos = instance.pos

    def _update_progress_bar(self, instance, value):
        self.progress_bg.size = instance.size
        self.progress_bg.pos = instance.pos
        self.progress_fill.pos = instance.pos

    def apply_theme(self, mode):
        t = THEMES[mode]
        self.bg_color_inst.rgba = t['bg']
        self.card_bg.rgba = t['card']
        self.link_input.foreground_color = t['text_primary']
        self.link_input.hint_text_color = t['text_secondary']
        self.link_input.update_style(t['bg'], t['card_border'])
        self.status_lbl.color = t['text_secondary']
        self.storage_info_lbl.color = t['text_secondary']
        self.download_btn.update_color(t['accent'])
        self.share_btn.update_color(t['accent_green'])

    def on_enter(self):
        app = App.get_running_app()
        self.apply_theme(app.current_theme)
        self.update_storage_display()

    # ---------- Storage management ----------
    def _get_install_timestamp(self):
        """Return the datetime when the app was first launched, or create it."""
        ts_file = os.path.join(get_app_storage_dir(), "install_date")
        if os.path.exists(ts_file):
            with open(ts_file, 'r') as f:
                stamp_str = f.read().strip()
            return datetime.datetime.fromisoformat(stamp_str)
        else:
            now = datetime.datetime.now()
            with open(ts_file, 'w') as f:
                f.write(now.isoformat())
            return now

    def _get_max_storage_bytes(self):
        install_time = self._get_install_timestamp()
        now = datetime.datetime.now()
        days_since_install = (now - install_time).days
        # 1 GB for first week, then 5 GB
        if days_since_install < 7:
            return 1 * 1024 * 1024 * 1024  # 1 GB
        else:
            return 5 * 1024 * 1024 * 1024  # 5 GB

    def _get_current_usage(self):
        total = 0
        for dirpath, dirnames, filenames in os.walk(self.download_dir):
            for fn in filenames:
                fp = os.path.join(dirpath, fn)
                total += os.path.getsize(fp)
        return total

    def update_storage_display(self):
        used = self._get_current_usage()
        max_bytes = self._get_max_storage_bytes()
        used_mb = used / (1024 * 1024)
        max_mb = max_bytes / (1024 * 1024)
        self.storage_info_lbl.text = f"Storage: {used_mb:.1f} MB / {max_mb:.1f} MB"

    def set_progress(self, value):
        if value < 0: value = 0
        elif value > 100: value = 100
        self.progress_fill.size = (self.progress_bar.width * value / 100, self.progress_bar.height)

    # ---------- Download logic ----------
    def start_download(self, instance):
        url = self.link_input.text.strip()
        if not url:
            self.status_lbl.text = "Please enter a link"
            return

        # Check storage limit before starting
        max_bytes = self._get_max_storage_bytes()
        current_usage = self._get_current_usage()
        if current_usage >= max_bytes:
            self.status_lbl.text = "Storage full! Delete some files or upgrade."
            return

        self.download_btn.disabled = True
        self.download_btn.text = "Downloading..."
        self.status_lbl.text = "Starting download..."
        self.set_progress(0)
        self.share_btn.opacity = 0
        self.share_btn.disabled = True

        # yt-dlp options – download to our internal folder
        ydl_opts = {
            'outtmpl': os.path.join(self.download_dir, '%(title)s.%(ext)s'),
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'progress_hooks': [self._ydl_progress_hook],
            'noplaylist': True,
            'quiet': True,
        }

        threading.Thread(target=self._download_thread, args=(url, ydl_opts, max_bytes, current_usage),
                         daemon=True).start()

    def _ydl_progress_hook(self, d):
        if d['status'] == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
            downloaded = d.get('downloaded_bytes', 0)
            if total > 0:
                percent = int(downloaded / total * 100)
            else:
                percent = 0
            Clock.schedule_once(lambda dt, p=percent: self.set_progress(p), 0)
        elif d['status'] == 'finished':
            Clock.schedule_once(lambda dt: self.set_progress(100), 0)
            Clock.schedule_once(lambda dt: setattr(self.status_lbl, 'text', 'Processing...'), 0)

    def _download_thread(self, url, ydl_opts, max_bytes, initial_usage):
        try:
            import yt_dlp
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                file_path = ydl.prepare_filename(info)

            # Check if the download would exceed the limit
            file_size = os.path.getsize(file_path)
            if initial_usage + file_size > max_bytes:
                os.remove(file_path)
                Clock.schedule_once(lambda dt: self._on_limit_exceeded(), 0)
                return

            self.downloaded_path = file_path
            Clock.schedule_once(self._on_download_finished, 0)
        except Exception as e:
            Clock.schedule_once(lambda dt: self._on_download_error(str(e)), 0)

    @mainthread
    def _on_download_finished(self, dt):
        self.download_btn.text = "⬇ Download"
        self.download_btn.disabled = False
        self.status_lbl.text = f"Saved: {os.path.basename(self.downloaded_path)}"
        self.share_btn.opacity = 1
        self.share_btn.disabled = False
        self.update_storage_display()

    @mainthread
    def _on_download_error(self, error_msg):
        self.download_btn.text = "⬇ Download"
        self.download_btn.disabled = False
        self.status_lbl.text = f"Error: {error_msg}"
        self.set_progress(0)

    @mainthread
    def _on_limit_exceeded(self):
        self.download_btn.text = "⬇ Download"
        self.download_btn.disabled = False
        self.status_lbl.text = "Storage limit would be exceeded. File not saved."
        self.set_progress(0)
        self.update_storage_display()

    # ---------- Sharing ----------
    def share_video(self, instance):
        if not self.downloaded_path:
            self.status_lbl.text = "No video to share"
            return
        self._share_file_android(self.downloaded_path)

    def _share_file_android(self, file_path):
        """Share a file via Android's share intent."""
        if not ANDROID_PLATFORM:
            self.status_lbl.text = "Sharing only on Android"
            return
        try:
            from jnius import autoclass, cast
            PythonActivity = autoclass('org.kivy.android.PythonActivity')
            Intent = autoclass('android.content.Intent')
            File = autoclass('java.io.File')
            Uri = autoclass('android.net.Uri')
            StrictMode = autoclass('android.os.StrictMode')

            StrictMode.VmPolicy.Builder().build()

            file = File(file_path)
            uri = Uri.fromFile(file)

            intent = Intent(Intent.ACTION_SEND)
            intent.setType('video/*')
            intent.putExtra(Intent.EXTRA_STREAM, uri)
            intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)

            currentActivity = cast('android.app.Activity', PythonActivity.mActivity)
            currentActivity.startActivity(Intent.createChooser(intent, "Share Video"))
        except Exception as e:
            self.status_lbl.text = f"Share failed: {str(e)}"


# ============================================================
#                        MAIN APP
# ============================================================
class TravelAssistantApp(App):
    current_theme = 'dark'
    touch_lock_enabled = True
    prayer_notify_enabled = False

    def build(self):
        init_db()
        self.sm = ScreenManager(transition=FadeTransition(duration=0.12))
        self.home_screen = HomeScreen(name="home")
        self.add_screen = AddPlaceScreen(name="add_place")
        self.nav_screen = NavigationScreen(name="navigation")
        self.settings_screen = SettingsScreen(name="settings")
        self.download_screen = DownloadScreen(name="download")   # <-- new

        self.sm.add_widget(self.home_screen)
        self.sm.add_widget(self.add_screen)
        self.sm.add_widget(self.nav_screen)
        self.sm.add_widget(self.settings_screen)
        self.sm.add_widget(self.download_screen)

        # Loading overlay
        self.loading_overlay = FloatLayout(size_hint=(1,1))
        with self.loading_overlay.canvas.before:
            Color(0,0,0,0.7)
            self._overlay_rect = Rectangle(size=self.loading_overlay.size, pos=self.loading_overlay.pos)
        self.loading_label = Label(text="Acquiring GPS...", font_size=sp(20), color=(1,1,1,1))
        self.loading_overlay.add_widget(self.loading_label)
        self.sm.add_widget(self.loading_overlay)

        Clock.schedule_once(self.start_permission_and_location, 1)
        return self.sm

    def start_permission_and_location(self, dt):
        self.request_android_permissions()

    def request_android_permissions(self):
        if ANDROID_PLATFORM:
            try:
                request_permissions([
                    Permission.ACCESS_FINE_LOCATION,
                    Permission.ACCESS_COARSE_LOCATION,
                    Permission.INTERNET,
                    Permission.ACCESS_NETWORK_STATE,
                    Permission.POST_NOTIFICATIONS
                ], self._on_permissions_result)
                return
            except Exception:
                pass
        self._do_initial_location()

    def _on_permissions_result(self, permissions, grants):
        Clock.schedule_once(lambda dt: self._do_initial_location(), 0)

    def _do_initial_location(self):
        def on_located(lat, lon):
            set_origin_location(lat, lon, "My Location")
            if self.loading_overlay in self.sm.screens:
                self.sm.remove_widget(self.loading_overlay)
            self.home_screen.on_enter()
        locate_once(on_located, timeout=30.0)

    def switch_theme(self, theme_name):
        self.current_theme = theme_name
        for screen in self.sm.screens:
            if hasattr(screen, 'apply_theme'):
                screen.apply_theme(theme_name)

if __name__ == "__main__":
    TravelAssistantApp().run()