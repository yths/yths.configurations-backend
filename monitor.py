import os
import time
import json

import schedule
import redis

def job(r):
    grid = True
    batteries = dict()
    for filename in os.listdir('/sys/class/power_supply/'):
        if filename.startswith('BAT'):
            with open(os.path.join('/sys/class/power_supply/', filename, 'capacity')) as f:
                capacity = f.read().strip()
            with open(os.path.join('/sys/class/power_supply/', filename, 'status')) as f:
                status = f.read().strip()
                if status == 'Discharging':
                    grid = False 
            batteries[filename] = {'capacity': capacity, 'status': status}
    r.xadd('power_supply', {"measurement": json.dumps({'grid': grid, 'batteries': batteries})})

if __name__ == "__main__":
    try:
        r = redis.Redis(host='localhost', port=6379, db=1)
        r.ping()
    except redis.exceptions.ConnectionError:
        sys.exit(1)
    
    schedule.every().second.do(job, r=r)
    while True:
        schedule.run_pending()
        time.sleep(1)
