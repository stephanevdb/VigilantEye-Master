from flask import Flask, render_template, request, redirect, url_for, session
import sqlite3
import os
import requests
import threading
from time import sleep
import json
from sqlite import dbinit, execute
from modules.ping import ping_target

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
                requests.get(f'http://{worker_ip}:8667/ping', timeout=1)
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

@app.route("/")
def index():
    return render_template('index.html')

@app.route('/submit_form', methods=['POST'])
def submit_form():
    target = request.form.get('target')
    ping_en = request.form.get('ping')
    ipv4_en = request.form.get('ipv4')
    ipv6_en = request.form.get('ipv6')
    print(target, ping_en, ipv4_en, ipv6_en)
    result_dict = {"Scans": {"Ping": None, "Trace": None}}

    output = ''
    if ping_en == 'ping':
        result_dict['Scans']['Ping'] = ping_target(target, ipv4_en, ipv6_en)

    output = json.dumps(result_dict, indent=2)
    session['output'] = output
    return redirect(url_for('output'))



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

@app.route("/output")
def output():
    try:
        output_json = session.get('output', '{}')
        output_dict = json.loads(output_json)
        #output = session.pop('output', None)
    except:
        output = 'No output'
    return render_template('output.html', output=output_dict)


if __name__ == "__main__":
    bg_thread = threading.Thread(target=check_worker)
    #bg_thread.daemon = True  # Set the thread as a daemon
    bg_thread.start()
    app.run(debug=False,host="0.0.0.0",port=8666)