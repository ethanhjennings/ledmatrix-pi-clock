import time
from datetime import datetime
import sys
import multiprocessing
import queue

import requests
from rgbmatrix import RGBMatrix, RGBMatrixOptions, graphics
from PIL import Image
import board

import adafruit_sht31d as sht31d
import adafruit_sgp30 as sgp30
import adafruit_veml7700 as veml7700

SENSOR_BASELINES_FILE = "baselines.txt"

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

def _map_co2_color(co2):
    if co2 < 1000: 
        return (0, 255, 0) 
    elif co2 < 2000: 
        return (255, 255, 0) 
    else: 
        return (255, 0, 0) 


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
    

def _refresh_internet_data(weather_queue):
    while True:
        weather_data = dict(EMPTY_WEATHER_DATA)

        r = requests.get('https://api.openweathermap.org/data/2.5/weather?lat=<YOUR LATTITUDE>&lon=<YOUR LONGITUDE>&appid=<YOUR API KEY HERE>&units=imperial')
        if r.status_code == 200:
            try:
                data = r.json()
                weather_data['temp']      = data['main']['temp']
                weather_data['low_temp']  = data['main']['temp_min']
                weather_data['high_temp'] = data['main']['temp_max']
                weather_data['humid']  = data['main']['humidity']
                weather_data['icon']      = data['weather']['icon']
            except:
                pass

        r = requests.get('https://ethanj.me/aqi/api?lat=<YOUR LATTITUDE>&lon=<YOUR LONGITUDE>&radius=2&correction=none')
        if r.status_code == 200:
            try:
                data = r.json()
                weather_data['aqi']       = data['aqi']
                weather_data['aqi_color'] = (data['color']['r'], data['color']['g'], data['color']['b'])
            except:
                pass

        weather_queue.put(weather_data)
        time.sleep(60*2)

class LEDClock:
    def __init__(self):
        self.matrix = RGBMatrix(options = self._get_options())
        self.offscreen_canvas = self.matrix.CreateFrameCanvas()

        self.time_font = graphics.Font()
        self.time_font.LoadFont('resources/fonts/8x20_numerics.bdf')
        self.small_font = graphics.Font()
        self.small_font.LoadFont('resources/fonts/3x5_numerics.bdf')
        self.date_font = graphics.Font()
        self.date_font.LoadFont('resources/fonts/4x5_text.bdf')
        self.am_pm_font = graphics.Font()
        self.am_pm_font.LoadFont('resources/fonts/am_pm.bdf')

        self.white = graphics.Color(255, 255, 255)
        self.purple = graphics.Color(81, 0, 255)
        self.am_color = graphics.Color(255, 255, 0)
        self.pm_color = graphics.Color(91, 72, 255)

        self.weather_img = Image.open('resources/weather_icons/mist.png').convert('RGB')
        self.inside_humid_img = Image.open('resources/symbol_icons/inside_humid.png').convert('RGB')
        self.outside_humid_img = Image.open('resources/symbol_icons/outside_humid.png').convert('RGB')
        self.co2_img = Image.open('resources/symbol_icons/co2.png').convert('RGB')
        self.aqi_img = Image.open('resources/symbol_icons/aqi.png').convert('RGB')
        self.inside_temp_img = Image.open('resources/symbol_icons/inside_temp.png').convert('RGB')
        self.outside_temp_img = Image.open('resources/symbol_icons/outside_temp.png').convert('RGB')
        self.high_temp_img = Image.open('resources/symbol_icons/high_temp.png').convert('RGB')
        self.low_temp_img = Image.open('resources/symbol_icons/low_temp.png').convert('RGB')

        self.weather_data = dict(EMPTY_WEATHER_DATA)
        self.weather_queue = multiprocessing.Queue()

        self.sensor_data = dict(EMPTY_SENSOR_DATA)
        self.sensor_queue = multiprocessing.Queue()

        self.internet_process = multiprocessing.Process(target=_refresh_internet_data, args=[self.weather_queue])
        self.internet_process.start()

        self.sensor_process = multiprocessing.Process(target=_refresh_sensor_data, args=[self.sensor_queue])
        self.sensor_process.start()

    def _get_options(self):
        options = RGBMatrixOptions()
        options.rows = 32
        options.cols = 64
        options.gpio_slowdown = 3
        options.drop_privileges = False
        return options

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

        hours = str(hours).rjust(2, ' ')
        minutes = str(now.minute).rjust(2, '0')
        seconds = str(now.second).rjust(2, '0')
        weekday = str(['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN'][now.weekday()])
        month = str(['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'][now.month-1])
        days = str(now.day)

        graphics.DrawText(canvas, self.time_font,  -6, 20, self.white, f'{hours}:{minutes}')
        graphics.DrawText(canvas, self.small_font, 37, 19, self.white, f'{seconds}')
        graphics.DrawText(canvas, self.date_font,   5, 26, self.white, f'{weekday} {month}')
        graphics.DrawText(canvas, self.small_font, 37, 26, self.white, f'{days}')

        inside_temp, inside_temp_color     = self._format_weather_datapoint(self.sensor_data['temp'], 2, True)
        outside_temp, outside_temp_color   = self._format_weather_datapoint(self.weather_data['temp'], 2, True)
        high_temp, high_temp_color         = self._format_weather_datapoint(self.weather_data['high_temp'], 2, True)
        low_temp,  low_temp_color          = self._format_weather_datapoint(self.weather_data['low_temp'], 2, True)
        outside_humid, outside_humid_color = self._format_weather_datapoint(self.weather_data['humid'], 2)
        inside_humid, inside_humid_color   = self._format_weather_datapoint(self.sensor_data['humid'], 2)

        co2, _                             = self._format_weather_datapoint(self.sensor_data['co2'], 4)
        co2_color = graphics.Color(*_map_co2_color(self.sensor_data['co2'])) if self.sensor_data['co2'] is not None else self.purple


        aqi, _                             = self._format_weather_datapoint(self.weather_data['aqi'], 3)
        aqi_color = graphics.Color(*self.weather_data['aqi_color']) if self.weather_data['aqi_color'] is not None else self.purple

        graphics.DrawText(canvas, self.small_font, 53, 5, inside_temp_color, f"{inside_temp}")
        graphics.DrawText(canvas, self.small_font, 53, 12, outside_temp_color, f"{outside_temp}")
        graphics.DrawText(canvas, self.small_font, 53, 19, high_temp_color, f"{high_temp}")
        graphics.DrawText(canvas, self.small_font, 53, 26, low_temp_color, f"{low_temp}")
        graphics.DrawText(canvas, self.small_font, 4, 32, outside_humid_color, f"{inside_humid}")
        graphics.DrawText(canvas, self.small_font, 17, 32, outside_humid_color, f"{outside_humid}")
        graphics.DrawText(canvas, self.small_font, 31, 32, co2_color, f"{co2}")
        graphics.DrawText(canvas, self.small_font, 53, 32, aqi_color, f"{aqi}")

        if (am):
            graphics.DrawText(canvas, self.am_pm_font, 45, 18, self.am_color, 'A')
        else:
            graphics.DrawText(canvas, self.am_pm_font, 45, 18, self.pm_color, 'P')

        # Draw weather icon
        canvas.SetImage(self.weather_img, 37, 1)
        
        # Draw symbol icons
        canvas.SetImage(self.inside_humid_img, 0, 27)
        canvas.SetImage(self.outside_humid_img, 13, 27)
        canvas.SetImage(self.co2_img, 27, 27)
        canvas.SetImage(self.aqi_img, 49, 27)
        canvas.SetImage(self.inside_temp_img, 49,  0)
        canvas.SetImage(self.outside_temp_img, 49, 7)
        canvas.SetImage(self.high_temp_img, 49, 14)
        canvas.SetImage(self.low_temp_img,  49, 21)

        try:
            self.weather_data = self.weather_queue.get_nowait()
        except queue.Empty:
            pass

        try:
            self.sensor_data = self.sensor_queue.get_nowait()
        except queue.Empty:
            pass
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