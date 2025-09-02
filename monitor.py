import json
import os
import platform
import subprocess
import sys
import time

import gi.repository.Gio
import redis
import requests
import schedule


def job_location(r, token=None):
    if token is not None:
        response = requests.get(f"https://ipinfo.io?token={token}")
        try:
            data = response.json()
            longitude = float(data["loc"].split(",")[1])
            latitude = float(data["loc"].split(",")[0])

            ip_address = data["ip"]
            timezone = data["timezone"]

            response = requests.get(
                f"https://api.sunrisesunset.io/json?lat={latitude}&lng={longitude}&timezone={data['timezone']}&time_format=24"
            )
            data = response.json()
            sunrise = data["results"]["sunrise"]
            sunset = data["results"]["sunset"]

            r.xadd(
                "location",
                {
                    "measurement": json.dumps(
                        {
                            "latitude": latitude,
                            "longitude": longitude,
                            "ip_address": ip_address,
                            "timezone": timezone,
                            "sunrise": sunrise,
                            "sunset": sunset,
                        }
                    )
                },
            )
        except requests.exceptions.JSONDecodeError:
            pass


def job_updates(r):
    if platform.freedesktop_os_release()["NAME"] != "Ubuntu":
        p = subprocess.Popen(
            "yay -Qua --color never | wc -l",
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout, _ = p.communicate()

        try:
            outstanding_updates = int(stdout.decode("utf-8").strip())
        except ValueError:
            outstanding_updates = 0

        p = subprocess.Popen(
            "checkupdates | wc -l",
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout, _ = p.communicate()

        try:
            outstanding_updates += int(stdout.decode("utf-8").strip())
        except ValueError:
            outstanding_updates += 0
    else:
        p = subprocess.Popen(
            "/usr/lib/update-notifier/apt-check",
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout, _ = p.communicate()

        try:
            outstanding_updates = int(stdout.decode("utf-8").split(";")[0])
        except ValueError:
            outstanding_updates = 0

    r.xadd(
        "updates",
        {"measurement": json.dumps({"outstanding_updates": outstanding_updates})},
    )


def job_bluetooth(r, manager):
    connected_devices = set()
    try:
        objects = manager.GetManagedObjects()
    except:
        objects = dict()
    for path, data in objects.items():
        status = data.get("org.bluez.Device1", {}).get("Connected", False)
        if status:
            address = data.get("org.bluez.Device1", {}).get("Address", "Unknown")
            try:
                capacity = data.get("org.bluez.Battery1", {}).get(
                    "Percentage", "Unknown"
                )
            except AttributeError:
                capacity = "Unknown"
            connected_devices.add((address, capacity))
    r.xadd(
        "bluetooth",
        {
            "measurement": json.dumps(
                {
                    device: {"capacity": capacity}
                    for device, capacity in connected_devices
                }
            )
        },
    )


def job_powersupply(r):
    grid = True
    batteries = dict()
    for filename in os.listdir("/sys/class/power_supply/"):
        if filename.startswith("BAT"):
            with open(
                os.path.join("/sys/class/power_supply/", filename, "capacity")
            ) as f:
                capacity = f.read().strip()
            with open(
                os.path.join("/sys/class/power_supply/", filename, "status")
            ) as f:
                status = f.read().strip()
                if status == "Discharging":
                    grid = False
            batteries[filename] = {"capacity": capacity, "status": status}
    r.xadd(
        "power_supply",
        {"measurement": json.dumps({"grid": grid, "batteries": batteries})},
    )


if __name__ == "__main__":
    try:
        r = redis.Redis(host=os.environ.get("YTHS_REDIS_HOST", "localhost"), port=int(os.environ.get("YTHS_REDIS_PORT", 6379)), db=int(os.environ.get("YTHS_REDIS_DB", 1)))
        r.ping()
    except redis.exceptions.ConnectionError:
        sys.exit(1)

    manager = gi.repository.Gio.DBusProxy().new_for_bus_sync(
        **{
            "bus_type": gi.repository.Gio.BusType.SYSTEM,
            "name": "org.bluez",
            "object_path": "/",
            "interface_name": "org.freedesktop.DBus.ObjectManager",
            "flags": gi.repository.Gio.DBusProxyFlags.NONE,
            "info": None,
            "cancellable": None,
        }
    )

    if os.path.exists(os.path.expanduser("~/.config/credentials.json")):
        with open(os.path.expanduser("~/.config/credentials.json")) as input_handle:
            credentials = json.load(input_handle)
    else:
        credentials = dict()

    schedule.every().second.do(job_bluetooth, r=r, manager=manager)
    schedule.every().second.do(job_powersupply, r=r)
    schedule.every().hour.do(job_updates, r=r)
    schedule.every().hour.at(":30").do(
        job_location, r=r, token=credentials.get("IPINFO_TOKEN")
    )

    schedule.run_all()
    while True:
        schedule.run_pending()
        time.sleep(1)
