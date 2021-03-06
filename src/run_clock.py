import time
from datetime import datetime, timedelta
import json
import queue
import multiprocessing
import re
import sys

from dateutil.tz import tzlocal
import ephem
import requests
from rgbmatrix import RGBMatrix, RGBMatrixOptions, graphics
from PIL import Image, ImageOps
from bdfparser import Font
import board
import socketio

import adafruit_sht31d as sht31d
import adafruit_sgp30 as sgp30
import adafruit_veml7700 as veml7700

CONFIG_FILE = "config.json"
SENSOR_BASELINES_FILE = "baselines.txt"

WEATHER_API_URL = "https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={key}&units=imperial"
PURPLEAIR_API_URL = "https://ethanj.me/aqi/api?lat={lat}&lon={lon}&radius=2&correction=none"
NWS_GRIDPOINT_API_URL = "https://api.weather.gov/points/{lat},{lon}"

EMPTY_WEATHER_DATA = {
    'temp': None,
    'low_temp': None,
    'high_temp': None,
    'humid': None,
    'icon': None,
    'aqi': None,
    'aqi_color': None,
}

EMPTY_SENSOR_DATA = {
    'humid': None,
    'temp': None,
    'co2': None,
}

WEATHER_ICONS_PATH = 'resources/weather_icons/'

WEATHER_ICONS = {
    '01d': 'clear_day.png',
    '01n': 'clear_night.png',
    '02d': 'few_clouds_day.png',
    '02n': 'few_clouds_night.png',
    '03d': 'scattered_clouds.png',
    '03n': 'scattered_clouds.png',
    '04d': 'broken_clouds.png',
    '04n': 'broken_clouds.png',
    '09d': 'shower_rain.png',
    '09n': 'shower_rain.png',
    '10d': 'rain.png',
    '10n': 'rain.png',
    '11d': 'thunderstorm.png',
    '11n': 'thunderstorm.png',
    '13d': 'snow.png',
    '13n': 'snow.png',
    '50d': 'mist.png',
    '50n': 'mist.png',
    'default': 'unkown.png'
}

def _handle_socketio(socketio_queue):

    connected = False
    while not connected:
        try:
            sio = socketio.Client()
            sio.connect('http://localhost')
            connected = True
        except socketio.exceptions.ConnectionError:
            pass
        time.sleep(1)

    state = {'enabled': True, 'brightness': 100}

    @sio.on('display_state')
    def message(data):
        nonlocal state
        state = data
        socketio_queue.put(state)

    # Mechanism to get state to state-less flask server when a new javascript client connnects
    @sio.on('get_state')
    def get_state():
        nonlocal state
        sio.emit('display_state', state)

def _map_co2_color(co2):
    if co2 < 1000: 
        return (96, 208, 62) # green
    elif co2 < 2000: 
        return (245, 253, 84) # yellow
    else: 
        return (234, 51, 36) # red


def _refresh_sensor_data(sensor_queue):
    # Load sensor baselines
    try:
        with open(SENSOR_BASELINES_FILE, 'r') as f:
            eco2_baseline, tvoc_baseline = [int(b.strip()) for b in f.readline().split(",")]
    except (FileNotFoundError, IOError, ValueError):
        eco2_baseline, tvoc_baseline = None, None
        print("ERROR: Unable to read baselines.txt, starting over baselines!")

    i2c = board.I2C()
    temp_humid = sht31d.SHT31D(i2c)
    air_sensor = sgp30.Adafruit_SGP30(i2c)
    air_sensor.iaq_init()
    if eco2_baseline is not None and tvoc_baseline is not None:
        air_sensor.set_iaq_baseline(eco2_baseline, tvoc_baseline)
    light_sensor = veml7700.VEML7700(i2c)
    
    sensor_data = dict(EMPTY_SENSOR_DATA)
    sensor_poll_timer = 0 # Force to trigger at startup
    save_baseline_timer = time.time()
    while True:
        if time.time() - sensor_poll_timer > 10:
            sensor_poll_timer = time.time()

            temp = temp_humid.temperature
            humid = temp_humid.relative_humidity

            air_sensor.set_iaq_relative_humidity(celcius=temp, relative_humidity=humid)
            co2 = air_sensor.iaq_measure()[0]

            sensor_data['temp'] = 9*temp/5+32
            sensor_data['humid'] = humid
            sensor_data['co2'] = co2
            if time.time() > save_baseline_timer + 60*60:
                save_baseline_timer = time.time()
                with open(SENSOR_BASELINES_FILE, 'w') as f:
                    print("Updating baselines:")
                    print(f"baseline_co2 = {air_sensor.baseline_eCO2}, baseline_voc = {air_sensor.baseline_TVOC}")
                    f.write(str(air_sensor.baseline_eCO2) + ',' + str(air_sensor.baseline_TVOC) + '\n')

        sensor_data['light'] = light_sensor.light
        sensor_queue.put(sensor_data)
        time.sleep(0.3)
    
def _iso_to_datetime_range(iso):
    """
    Convert an iso date string with duration to start and end datetime objects
    Example input: "2022-06-05T17:00:00+00:00/PT14H"
    Returns (datetime, datetime)
    """

    try:
        start_str, duration_str = iso.split('/')
        start_utc = datetime.fromisoformat(start_str)
    except ValueError:
        return None, None

    start = start_utc.astimezone(tzlocal())

    match = re.match(r'PT(\d+)H', duration_str)
    if not match:
        return None, None

    duration_hrs = match.group(1)

    end = start + timedelta(hours=int(duration_hrs))

    return start, end

def _to_f(c):
    ''' Convert to farenheight '''
    return (float(c)*9/5) + 32

def _refresh_internet_data(weather_queue):
    with open(CONFIG_FILE) as f:
        config = json.load(f)

    while True:
        weather_data = dict(EMPTY_WEATHER_DATA)
        network_error = False
        nws_forecast_api_url = None

        try:
            r = requests.get(WEATHER_API_URL.format(lat=config['lat'], lon=config['lon'], key=config['openweather_api_key']))
            if r.status_code == 200:
                try:
                    data = r.json()
                    weather_data['temp']      = data['main']['temp']
                    weather_data['humid']     = data['main']['humidity']
                    weather_data['icon']      = data['weather'][0]['icon']
                except KeyError:
                    print("Openweather data poorly formatted!")
        except requests.exceptions.RequestException:
            network_error = True
            print("Network error!")

        try:
            r = requests.get(PURPLEAIR_API_URL.format(lat=config['lat'], lon=config['lon']))
            if r.status_code == 200:
                try:
                    data = r.json()
                    weather_data['aqi']       = data['aqi']
                    weather_data['aqi_color'] = (data['color']['r'], data['color']['g'], data['color']['b'])
                except KeyError:
                    print("Purpleair dash data poorly formatted!")
        except requests.exceptions.RequestException:
            network_error = True
            print("Network error!")

        if not nws_forecast_api_url:
            try:
                r = requests.get(NWS_GRIDPOINT_API_URL.format(lat=config['lat'], lon=config['lon']))
                if r.status_code == 200:
                    try:
                        data = r.json()
                        nws_forecast_api_url = data['properties']['forecastGridData']
                    except KeyError:
                        print("Error parsing NWS data")
            except requests.exceptions.RequestException:
                network_error = True
                print("Network error!")

        try:
            r = requests.get(nws_forecast_api_url)
            if r.status_code == 200:
                try:
                    now = datetime.now()
                    data = r.json()
                    now = datetime.now().astimezone(tzlocal())

                    for data_point in data['properties']['minTemperature']['values']:
                        start, end = _iso_to_datetime_range(data_point['validTime'])
                        if end > now:
                            weather_data['low_temp'] = _to_f(data_point['value'])

                    for data_point in data['properties']['maxTemperature']['values']:
                        start, end = _iso_to_datetime_range(data_point['validTime'])
                        if end > now:
                            weather_data['high_temp'] = _to_f(data_point['value'])
                except KeyError:
                    print("Error parsing NWS data")
        except requests.exceptions.RequestException:
            network_error = True
            print("Network error!")

        weather_queue.put(weather_data)
        if not network_error:
            time.sleep(60*2)
        else:
            # Keep checking network more frequently in case it's back up
            time.sleep(0.5)

class LEDClock:
    def __init__(self):
        self.matrix = RGBMatrix(options = self._get_options())
        self.offscreen_canvas = self.matrix.CreateFrameCanvas()

        with open(CONFIG_FILE) as f:
            self.config = json.load(f)
        self.high_temp_start = datetime.strptime(self.config["high_temp_start"], "%H:%M").time()
        self.high_temp_end = datetime.strptime(self.config["high_temp_end"], "%H:%M").time()

        self.matrix.brightness = 0
        self.enabled = True
        self.brightness = 0
        self.target_brightness = 100

        self.time_font = graphics.Font()
        self.time_font.LoadFont('resources/fonts/8x20_numerics.bdf')
        self.small_font = graphics.Font()
        self.small_font.LoadFont('resources/fonts/3x5_numerics.bdf')
        self.date_font = Font('resources/fonts/4x5_text.bdf')

        self.am_pm_font = graphics.Font()
        self.am_pm_font.LoadFont('resources/fonts/am_pm.bdf')

        self.white = graphics.Color(255, 255, 255)
        self.purple = graphics.Color(81, 0, 255)
        self.am_color = graphics.Color(255, 255, 0)
        self.pm_color = graphics.Color(120, 120, 255)

        self.inside_humid_img = Image.open('resources/symbol_icons/inside_humid.png').convert('RGB')
        self.outside_humid_img = Image.open('resources/symbol_icons/outside_humid.png').convert('RGB')
        self.co2_img = Image.open('resources/symbol_icons/co2.png').convert('RGB')
        self.aqi_img = Image.open('resources/symbol_icons/aqi.png').convert('RGB')
        self.inside_temp_img = Image.open('resources/symbol_icons/inside_temp.png').convert('RGB')
        self.outside_temp_img = Image.open('resources/symbol_icons/outside_temp.png').convert('RGB')
        self.high_temp_img = Image.open('resources/symbol_icons/high_temp-color.png').convert('RGB')
        self.low_temp_img = Image.open('resources/symbol_icons/low_temp-color.png').convert('RGB')
        self.sunrise_img = Image.open('resources/symbol_icons/sunrise.png').convert('RGB')
        self.sunset_img = Image.open('resources/symbol_icons/sunset.png').convert('RGB')

        self.weather_icons = {}
        for icon_id, filename in WEATHER_ICONS.items():
            self.weather_icons[icon_id] = Image.open(WEATHER_ICONS_PATH + filename).convert('RGB')


        self.weather_data = dict(EMPTY_WEATHER_DATA)
        self.weather_queue = multiprocessing.Queue()

        self.sensor_data = dict(EMPTY_SENSOR_DATA)
        self.sensor_queue = multiprocessing.Queue()

        self.socketio_queue = multiprocessing.Queue()

        self.internet_process = multiprocessing.Process(target=_refresh_internet_data, args=[self.weather_queue])
        self.internet_process.start()

        self.sensor_process = multiprocessing.Process(target=_refresh_sensor_data, args=[self.sensor_queue])
        self.sensor_process.start()

        self.socketio_process = multiprocessing.Process(target=_handle_socketio, args=[self.socketio_queue])
        self.socketio_process.start()

    def _get_options(self):
        options = RGBMatrixOptions()
        options.rows = 32
        options.cols = 64
        options.gpio_slowdown = 3
        options.drop_privileges = False
        return options


    def _get_sun_set_rise_time(self):
        ''' Get either the sunrise or sunset time depending on which is sooner '''

        def to_degrees_str(decimal):
            minutes = 60*(decimal - int(decimal))
            seconds = 60*(minutes - int(minutes))
            return f"{int(decimal)}:{int(minutes)}:{seconds}"

        o = ephem.Observer()
        o.lat = to_degrees_str(self.config['lat'])
        o.long = to_degrees_str(self.config['lon'])
        o.date = datetime.utcnow()

        sun = ephem.Sun(o)
        sunrise = ephem.localtime(o.next_rising(sun))
        sunset = ephem.localtime(o.next_setting(sun))

        if sunrise < sunset:
            return sunrise, True
        else:
            return sunset, False

    def _format_weather_datapoint(self, datapoint, size, leading_space=False):
        if datapoint is not None:
            output = str(round(float(datapoint))).rjust(size, '0')
            if leading_space and datapoint < pow(10, size) and datapoint >= 0:
                output = " " + output
            return output, self.white
        else:
            output = "?"*size
            if leading_space:
                output = " " + output
            return output, self.purple

    def _draw_loop(self):
        start_loop = time.time()
        canvas = self.offscreen_canvas
        canvas.Clear()

        now = datetime.now()
        hours = now.hour
        am = True
        if hours > 12:
            hours -= 12
            am = False
        if hours == 0:
            hours = 12

        hours = str(hours).rjust(2, ' ')
        minutes = str(now.minute).rjust(2, '0')
        seconds = str(now.second).rjust(2, '0')
        weekday = str(['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN'][now.weekday()])
        month = str(['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'][now.month - 1])
        days = str(now.day)

        graphics.DrawText(canvas, self.time_font,  -6, 20, self.white, f'{hours}:{minutes}')
        graphics.DrawText(canvas, self.small_font, 37, 19, self.white, f'{seconds}')
        byte_img = self.date_font.draw(f'{weekday} {month} {days}')
        img = ImageOps.invert(Image.frombytes('RGB', (byte_img.width(), byte_img.height()), byte_img.tobytes('RGB'))).convert('RGB')
        center_x = 25
        canvas.SetImage(img, center_x - byte_img.width()//2, 21)

        inside_temp, inside_temp_color     = self._format_weather_datapoint(self.sensor_data['temp'], 2, True)
        outside_temp, outside_temp_color   = self._format_weather_datapoint(self.weather_data['temp'], 2, True)
        high_temp, high_temp_color         = self._format_weather_datapoint(self.weather_data['high_temp'], 2, True)
        low_temp, low_temp_color           = self._format_weather_datapoint(self.weather_data['low_temp'], 2, True)
        outside_humid, outside_humid_color = self._format_weather_datapoint(self.weather_data['humid'], 2)
        inside_humid, inside_humid_color   = self._format_weather_datapoint(self.sensor_data['humid'], 2)

        sun_time, is_sunrise = self._get_sun_set_rise_time()
        sun_time = sun_time.strftime("%-I:%M")
        sun_time_icon = self.sunrise_img if is_sunrise else self.sunset_img

        co2, _                             = self._format_weather_datapoint(self.sensor_data['co2'], 4)
        co2_color = graphics.Color(*_map_co2_color(self.sensor_data['co2'])) if self.sensor_data['co2'] is not None else self.purple

        aqi, _                             = self._format_weather_datapoint(self.weather_data['aqi'], 3)
        aqi_color = graphics.Color(*self.weather_data['aqi_color']) if self.weather_data['aqi_color'] is not None else self.purple

        graphics.DrawText(canvas, self.small_font, 53, 5, inside_temp_color, f"{inside_temp}")
        graphics.DrawText(canvas, self.small_font, 53, 12, outside_temp_color, f"{outside_temp}")
        graphics.DrawText(canvas, self.small_font, 51, 26, self.white, f"{sun_time}")
        graphics.DrawText(canvas, self.small_font, 4, 32, outside_humid_color, f"{inside_humid}")
        graphics.DrawText(canvas, self.small_font, 17, 32, outside_humid_color, f"{outside_humid}")
        graphics.DrawText(canvas, self.small_font, 31, 32, co2_color, f"{co2}")
        graphics.DrawText(canvas, self.small_font, 53, 32, aqi_color, f"{aqi}")

        now = datetime.now().time()
        if now > self.high_temp_start and now < self.high_temp_end:
            graphics.DrawText(canvas, self.small_font, 53, 19, high_temp_color, f"{high_temp}")
            canvas.SetImage(self.high_temp_img, 49, 14)
        else:
            graphics.DrawText(canvas, self.small_font, 53, 19, low_temp_color, f"{low_temp}")
            canvas.SetImage(self.low_temp_img, 49, 14)

        if (am):
            graphics.DrawText(canvas, self.am_pm_font, 45, 18, self.am_color, 'A')
        else:
            graphics.DrawText(canvas, self.am_pm_font, 45, 18, self.pm_color, 'P')

        # Draw weather icon
        if self.weather_data['icon'] in self.weather_icons:
            icon = self.weather_icons[self.weather_data['icon']]
        else:
            icon = self.weather_icons['default']
        canvas.SetImage(icon, 37, 1)

        # Draw symbol icons
        canvas.SetImage(self.inside_humid_img, 0, 27)
        canvas.SetImage(self.outside_humid_img, 13, 27)
        canvas.SetImage(self.co2_img, 27, 27)
        canvas.SetImage(self.aqi_img, 49, 27)
        canvas.SetImage(self.inside_temp_img, 49,  0)
        canvas.SetImage(self.outside_temp_img, 49, 7)
        canvas.SetImage(sun_time_icon, 46, 22)

        try:
            self.weather_data = self.weather_queue.get_nowait()
        except queue.Empty:
            pass

        try:
            self.sensor_data = self.sensor_queue.get_nowait()
        except queue.Empty:
            pass

        try:
            state = self.socketio_queue.get_nowait()
            self.enabled = state['enabled']
            if self.enabled:
                self.target_brightness = float(state['brightness'])
            else:
                self.target_brightness = 0
        except queue.Empty:
            pass

        # Update brightness
        if self.target_brightness > self.brightness:
            self.brightness += 2.0
            self.brightness = min(self.brightness, 100)
        elif self.target_brightness < self.brightness:
            self.brightness -= 2.0
            self.brightness = max(self.brightness, 0)

        self.matrix.brightness = self.brightness
        self.offscreen_canvas = self.matrix.SwapOnVSync(self.offscreen_canvas)
        end_loop = time.time() - start_loop

    def run(self):
        try:
            # Start loop
            print('Press CTRL-C to stop')
            while True:
                self._draw_loop()
        except KeyboardInterrupt:
            print('Exiting\n')
            sys.exit(0)

if __name__ == '__main__':
    clock = LEDClock()
    clock.run()
