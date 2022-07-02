# ledmatrix-pi-clock
Code for an LED matrix clock and weather/air quality display running on a raspberry pi

# Installation and Setup
## Hardware
You need a rasbperry pi 4 or greater, an Adafruit RGB Matrix HAT (or similar), RGB matrix, and sensors (I'm using sht31d, sgp30, and veml7700 from Adafruit).

[Follow Adafruit's tutorial to setup the pi with the hat here](https://learn.adafruit.com/adafruit-rgb-matrix-plus-real-time-clock-hat-for-raspberry-pi)

## Main clock script
[See this part of the Adafruit tutorial in particular about setting up the software](https://learn.adafruit.com/adafruit-rgb-matrix-plus-real-time-clock-hat-for-raspberry-pi/driving-matrices#step-6-log-into-your-pi-to-install-and-run-software-1745233)

Once that's all working, you can install this repo by cloning it and installing the `requirements.txt`. The `rgbmatrix` module unfortunatley requires running as root, so it's easiest to not use a virtual environment.

```
pip install -r requirements.txt
```

### Config file

Then copy the config file and edit it:

```
cp example.config.json config.json
```

You're going to need an [OpenWeatherAPI key](https://openweathermap.org/api) (a free key works fine), and put it in the config file. Also update the `lat` and `lon` with your current lat/lon to get local weather data.

### Running Clock

> Unfortunatley the `rgbmatrix` module needs root access to work

Run the clock from the root of the project:

```
sudo python3 src/run_clock.py
```

I like to run this as a service so it persists between reboots. I put the service files at this path: `/etc/systemd/system/...`. [You can see my examples here]( https://github.com/ethanhjennings/ledmatrix-pi-clock/tree/main/example_services)

and run it with:
```
systemd restart ledclock
```

If it works, you can set it to run at boot with:

```
systemd enable ledclock
```

## Webserver

The webserver is optional, but nice for controlling the clock. I reccomend using a virtual environment for this one since it doesn't need to be root. Once you make that, install the dependencies in `webserver/requirements.txt`.

To run flask either use root with app.py (easy but insecure) or install a middleware like gunicorn.

I reccomend setting up a service in the same way as with the main clock script, and [you can see my examples here.]( https://github.com/ethanhjennings/ledmatrix-pi-clock/tree/main/example_services)
