from flask import Flask, render_template, request, redirect, url_for, session
import sqlite3
import os
import requests
import threading
from time import sleep
import json
from sqlite import dbinit, execute
import asyncio
from concurrent.futures import ThreadPoolExecutor

executor = ThreadPoolExecutor()

MODULES_PATH = 'modules'

def get_available_modules():
    available_modules = []
    for file in os.listdir(MODULES_PATH):
        if file.endswith('.py'):
            available_modules.append(file[:-3])
    return available_modules

def get_online_worker():
    cursor = execute('SELECT * FROM workers WHERE online = 1')
    workers = cursor.fetchall()

    for worker in workers:
        worker_id = worker[0]
        worker_ip = worker[6]
        try:
            res = requests.get(f'http://{worker_ip}:8667/ping', timeout=1)
            returned_worker_id, state = res.text.split(',')
            
            if returned_worker_id == worker_id and state.strip().lower() == 'idle':
                return {
                    'id': worker_id,
                    'ipv4_capable': worker[2],
                    'ipv4_address': worker[3],
                    'ipv6_capable': worker[4],
                    'ipv6_address': worker[5],
                    'worker_ip': worker_ip
                }
        except requests.exceptions.RequestException as e:
            print(f"Error getting worker status: {e}")
            pass

    return None


def upload_files(worker_ip,selected_module):
    file_path = os.path.join(MODULES_PATH, f'{selected_module}.py')
    req_path = os.path.join(MODULES_PATH, f'{selected_module}.txt')
    print(file_path)
    print(req_path)
    try:
        with open(file_path, 'rb') as f:
            f.seek(0)
            file = {'file': (os.path.basename(file_path), f)}
            url = f'http://{worker_ip}:8667/upload'
            r = requests.post(url, files=file)
            if r.status_code == 200:
                print(f"File {file_path} uploaded successfully")
            else:
                print(f"File upload failed with status code {r.status_code}")

    except requests.exceptions.RequestException as e:
        print("Error uploading file:", e)
        return 'Error uploading file', 500
    try:
        with open(req_path, 'rb') as f:
            f.seek(0)
            file = {'file': (os.path.basename(req_path), f)}
            url = f'http://{worker_ip}:8667/upload'
            r = requests.post(url, files=file)
            if r.status_code == 200:
                print(f"File {req_path} uploaded successfully")
            else:
                print(f"File upload failed with status code {r.status_code}")
    except requests.exceptions.RequestException as e:
        print("Error uploading file:", e)
        return 'Error uploading file', 500

def get_available_modules():
    available_modules = []
    for file in os.listdir(MODULES_PATH):
        if file.endswith('.py'):
            available_modules.append(file[:-3])
    return available_modules

worker_port = os.getenv('WORKER_PORT')
if not worker_port:
    master_port = 8666

app = Flask(__name__)
app.secret_key = os.urandom(24)
dbinit()

def check_worker():
    while True:
        print('Checking workers')
        cursor = execute('SELECT * FROM workers')
        workers = cursor.fetchall()
        for worker in workers:
            worker_id = worker[0]
            worker_ip = worker[6]
            try:
                res = requests.get(f'http://{worker_ip}:8667/ping', timeout=1)
                returned_worker_id = res.text.split(',')[0]
                if returned_worker_id != worker_id:
                    execute('UPDATE workers SET online = 0 WHERE id = ?', (worker_id,))
                    print(f'Worker {worker_id} is offline')
                    continue
                execute('UPDATE workers SET online = 1 WHERE id = ?', (worker_id,))
                print(f'Worker {worker_id} is online')
            except requests.exceptions.RequestException as e:
                execute('UPDATE workers SET online = 0 WHERE id = ?', (worker_id,))
                print(f'Worker {worker_id} is offline')
        sleep(5)




@app.route('/add_worker', methods=['POST'])
def add_worker():
    data = request.data.decode('utf-8')
    worker_id, ipv4_capable, ipv4_address, ipv6_capable, ipv6_address = data.split(',')
    ipv4_capable = int(ipv4_capable == 'True')
    ipv6_capable = int(ipv6_capable == 'True')
    worker_ip= request.environ.get('HTTP_X_REAL_IP', request.remote_addr)   
    online = 0
    execute('INSERT INTO workers (id, online, ipv4_capable, ipv4_address, ipv6_capable, ipv6_address, worker_ip) VALUES (?, ?, ?, ?, ?, ?, ?)', (worker_id, online, ipv4_capable, ipv4_address, ipv6_capable, ipv6_address, worker_ip))
    return 'Worker added successfully'

@app.route('/remove_worker', methods=['GET','POST'])
def remove_worker():
    if request.method == 'POST':
        data = request.form.get('id')
        worker_id = data
        execute('DELETE FROM workers WHERE id = ?', (worker_id,))
        return redirect(url_for('settings'))
    else:
        return 'Method Not Allowed', 405  

@app.route('/remove_scan', methods=['GET','POST'])
def remove_scan():
    if request.method == 'POST':
        data = request.form.get('id')
        scan_id = data
        execute('DELETE FROM scans WHERE id = ?', (scan_id,))
        return redirect(url_for('scans'))
    else:
        return 'Method Not Allowed', 405

@app.route("/")
def index():
    return render_template('index.html', available_modules=get_available_modules())

@app.route('/submit_form', methods=['POST'])
def submit_form():
    target = request.form.get('target')
    selected_modules = request.form.getlist('modules')
    ipv4_en = request.form.get('ipv4')
    ipv6_en = request.form.get('ipv6')
    result_dict = {"Scans": {}}

    async def process_modules():
        loop = asyncio.get_event_loop()

        tasks = [loop.run_in_executor(executor, process_module, target, ipv4_en, ipv6_en, module) for module in selected_modules]
        await asyncio.gather(*tasks)

    asyncio.run(process_modules())

    output = json.dumps(result_dict, indent=2)
    session['output'] = output
    return redirect(url_for('scans'))

def process_module(target, ipv4_en, ipv6_en, module):
    worker = get_online_worker()

    if worker:
        print(f"Sending job to worker {worker['id']} for module {module}")
        data = f"{module},{target},{ipv4_en},{ipv6_en}"
        try:
            upload_files(worker['worker_ip'], module)
            res = requests.post(f'http://{worker["worker_ip"]}:8667/job', data=data)
            cur = execute('INSERT INTO scans (target, worker_id, output, module) VALUES (?, ?, ?, ?)', (target, worker['id'], res.text, module))
            print(f"Job sent to worker {worker['id']} for module {module}")
        except requests.exceptions.RequestException as e:
            print(f"Error sending job for module {module}: {e}")
    else:
        print(f"No online workers available for module {module}")


    

@app.route("/settings")
def settings():

    cursor = execute('SELECT * FROM workers WHERE online = 1') 
    rows = cursor.fetchall()
    active_workers = []

    for row in rows:
        active_workers.append({
            'id': row[0],
            'ipv4_capable': row[2],  
            'ipv4_address': row[3],  
            'ipv6_capable': row[4], 
            'ipv6_address': row[5]  
        })
    cursor = execute('SELECT * FROM workers WHERE online = 0')  
    rows = cursor.fetchall()
    dead_workers = []

    for row in rows:
        dead_workers.append({
            'id': row[0],
            'ipv4_capable': row[2],
            'ipv4_address': row[3], 
            'ipv6_capable': row[4],  
            'ipv6_address': row[5]  
        })
    return render_template('settings.html', dead_workers=dead_workers, active_workers=active_workers)

@app.route("/test")
def test():
    return render_template('test.html'), 200

@app.route('/scan/<int:scan_id>')
def scan(scan_id):
    print(f"Scan ID: {scan_id}")
    cursor = execute('SELECT * FROM scans WHERE id = ?', (scan_id,))
    scan = cursor.fetchone()
    x = scan[3]
    y = json.loads(x)
    print(y)
    if scan:
        return render_template('scan_output.html', scan=y)
    else:
        return 'Scan not found', 404

@app.route("/scans")
def scans():
    cursor = execute('SELECT * FROM scans')
    rows = cursor.fetchall()
    output_dict = []
    for row in rows:
        output_dict.append({
            'id': row[0],
            'target': row[1],
            'worker_id': row[2],
            'output': row[3],
            'time': row[4],
            'module': row[5]
        })
    return render_template('scans.html', output=output_dict)


if __name__ == "__main__":
    bg_thread = threading.Thread(target=check_worker)
    #bg_thread.daemon = True  # Set the thread as a daemon
    bg_thread.start()
    app.run(debug=False,host="0.0.0.0",port=8666)