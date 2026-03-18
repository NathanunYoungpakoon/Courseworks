import flask
import requests

import sqlite3
import hashlib
import secrets
import time


APP = flask.Flask(__name__)
APP.secret_key = '943d52b288439275c33dd1b29a6fdf87'

DATABASE = 'database.sqlite3'

SESSION = requests.Session()
SESSION.headers['x-goog-api-key'] = 'AIzaSyBIcB_VqrgYpXNbaxPVMx0JKwftueFlIv8'
API_URL = 'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent'


@APP.route('/')
def index():
    return flask.render_template('index.html')


@APP.get('/signup')
def signup_get():
    if 'email' in flask.session:
        return flask.redirect(flask.url_for('index'))
    return flask.render_template('signup.html')


@APP.post('/signup')
def signup_post():
    try:
        email = flask.request.json['email']
        password = flask.request.json['password']
        
        h = hashlib.blake2b(key=APP.secret_key.encode(), digest_size=16)
        h.update(password.encode())
        hashed_password = h.hexdigest()
        
        db = get_db()
        c = db.cursor()
        account_type_id = c.execute('SELECT id FROM AccountType WHERE name="Customer"').fetchone()[0]
        data = (email, hashed_password, account_type_id)
        
        c.execute("""
            INSERT INTO Account (
                email,
                hashed_password,
                account_type_id
            ) VALUES (?, ?, ?)
        """, data)
        
        c.execute("""
            INSERT INTO Person (
                email
            ) VALUES (?)
        """, (email,))

        subscription_plan_id= c.execute('SELECT id FROM SubscriptionPlan WHERE name="Free"').fetchone()[0]
        payment_method_id= c.execute('SELECT id FROM PaymentMethod WHERE name="None"').fetchone()[0]
        signup_datetime = int(time.time())
        subscription_expire_datetime = 0

        data = (email, subscription_plan_id, payment_method_id, signup_datetime, subscription_expire_datetime)
        c.execute("""
            INSERT INTO Customer (
                email,
                subscription_plan_id,
                payment_method_id,
                signup_datetime,
                subscription_expire_datetime
            ) VALUES (?, ?, ?, ?, ?)
        """, data)
        
        return {'status': 'ok', 'message' : 'OK'}, 200
    except sqlite3.Error as err:
        if err.sqlite_errorcode == sqlite3.SQLITE_CONSTRAINT_PRIMARYKEY:
            return {'status': 'failed', 'message' : 'email is already taken'}, 403
        else:
            return {'status': 'failed', 'message' : err.args[0]}, 403


@APP.get('/login')
def login_get():
    if 'email' in flask.session:
        return flask.redirect(flask.url_for('index'))
    return flask.render_template('login.html')


@APP.post('/login')
def login_post():
    email = flask.request.json['email']
    password = flask.request.json['password']
    
    h = hashlib.blake2b(key=APP.secret_key.encode(), digest_size=16)
    h.update(password.encode())
    hashed_password = h.hexdigest()
    
    db = get_db()
    c = db.cursor()
    hashed_password_db, account_type_id = c.execute('SELECT hashed_password, account_type_id FROM Account WHERE email=?', (email,)).fetchone()

    if hashed_password_db is None:
        return {'message' : 'email does not exist'}, 403
    elif not secrets.compare_digest(hashed_password.encode(), hashed_password_db.encode()):
        return {'message' : 'password is incorrect'}, 403
        
    flask.session['email'] = email
    flask.session['account_type'] = account_type_id
    return {'message' : 'ok'}, 200


@APP.route('/logout')
def logout():
    flask.session.pop('email', None)
    flask.session.pop('account_type', None)
    return flask.redirect(flask.url_for('index'))


@APP.get('/chat')
def chat_get():
    if 'email' not in flask.session:
        return flask.redirect(flask.url_for('login_get'))

    return flask.render_template('chat.html')


@APP.get('/chat/init')
def chat_init_get():
    if 'email' not in flask.session:
        flask.abort(403)

    db = get_db()
    c = db.cursor()
    email = flask.session["email"]
    
    session_id = c.execute('SELECT MAX(session_id) FROM ChatLog').fetchone()[0]
    session_id = session_id + 1 if session_id is not None else 1
    
    log_number = 1
    datetime = int(time.time())
    message = f'Hello {email}! What can I do for you today?'

    try:
        data = (session_id, log_number, datetime, message, 'Chatbot')
        c.execute("""
            INSERT INTO ChatLog (
                session_id,
                log_number,
                datetime,
                message,
                email
            ) VALUES (?, ?, ?, ?, ?)
        """, data)
    except sqlite3.Error as err:
        return {'status': 'failed', 'message' : err.args[0]}, 403

    return {"session_id": session_id, "email": email}, 200


@APP.get('/chat/<int:session_id>')
def chat_session_get(session_id):
    if 'email' not in flask.session:
        flask.abort(403)
        
    db = get_db()
    c = db.cursor()

    data = []
    logs = c.execute('SELECT message, email FROM ChatLog WHERE session_id=? ORDER BY log_number', (session_id,)).fetchall()
    for message, email in logs:
        if message.startswith('FORWARD TO OPERATOR:'):
            message = 'Please wait ...'
        elif message.startswith('REPLY FROM OPERATOR:'):
            continue
            
        data.append(dict(message=message, email=email))

    return data, 200


@APP.post('/chat/<int:session_id>')
def chat_session_post(session_id):
    if 'email' not in flask.session:
        flask.abort(403)
        
    message = flask.request.json['message']
    email = flask.session["email"]

    err_msg = add_to_chat(session_id, email, message)
    if err_msg:
        return {'status': 'failed', 'message' : err_msg}, 403

    sys_inst = get_db().cursor().execute('SELECT text FROM SystemPrompt WHERE id=1').fetchone()[0]

    data = {'system_instruction': {'parts': [{"text": sys_inst}]}}
    data['contents'] = get_ai_chat_contents(session_id)

    # print(data)
    response = SESSION.post(API_URL, json=data)
    response.raise_for_status()
    ai_text = response.json()['candidates'][0]['content']['parts'][0]['text']
    
    err_msg = add_to_chat(session_id, 'Chatbot', ai_text)
    if err_msg:
        return {'status': 'failed', 'message' : err_msg}, 403
    
    return {'message' : 'ok'}, 200


@APP.get('/support/list')
def support_list_get():
    if 'email' not in flask.session or flask.session['account_type'] != 4:
        flask.abort(403)

    db = get_db()
    c = db.cursor()

    data = []
    results = c.execute('SELECT session_id, log_number, message, email FROM ChatLog WHERE reply_to=-1 ORDER BY datetime DESC').fetchall()
    for session_id, log_number, message, email in results:
        data.append({
            'id': f'{session_id}-{log_number}', 'email': email, 'message': message, 'reply': None
        })

    return data, 200


@APP.post('/support/list')
def support_list_post():
    if 'email' not in flask.session or flask.session['account_type'] != 4:
        flask.abort(403)

    email = flask.session["email"]
    
    chat_id = flask.request.json['id']
    reply = flask.request.json['reply']

    session_id, log_number = list(map(int, chat_id.split('-')))
    reply = 'REPLY FROM OPERATOR: ' + reply
    
    err_msg = add_to_chat(session_id, email, reply, log_number)
    if err_msg:
        return {'status': 'failed', 'message' : err_msg}, 403

    sys_inst = get_db().cursor().execute('SELECT text FROM SystemPrompt WHERE id=1').fetchone()[0]

    data = {'system_instruction': {'parts': [{"text": sys_inst}]}}
    data['contents'] = get_ai_chat_contents(session_id)

    response = SESSION.post(API_URL, json=data)
    response.raise_for_status()
    ai_text = response.json()['candidates'][0]['content']['parts'][0]['text']
    
    err_msg = add_to_chat(session_id, 'Chatbot', ai_text, log_number)
    if err_msg:
        return {'status': 'failed', 'message' : err_msg}, 403

    db = get_db()
    c = db.cursor()
    try:
        data = (session_id, log_number)
        c.execute('UPDATE ChatLog SET reply_to=0 WHERE session_id=? AND log_number=?', data)
    except sqlite3.Error as err:
        return {'status': 'failed', 'message' : err.args[0]}, 403
    
    return {'message' : 'ok'}, 200

    
@APP.route('/support')
def support():
    if 'email' not in flask.session or flask.session['account_type'] != 4:
        flask.abort(403)

    return flask.render_template('support.html')


@APP.route('/account')
def account():
    if 'email' not in flask.session or flask.session['account_type'] != 4:
        flask.abort(403)

    return flask.render_template('account.html')


@APP.get('/account/list')
def account_list_get():
    if 'email' not in flask.session or flask.session['account_type'] != 4:
        flask.abort(403)

    db = get_db()
    c = db.cursor()

    data = []
    
    customers = c.execute('SELECT email, subscription_plan_id, payment_method_id, signup_datetime, subscription_expire_datetime FROM Customer').fetchall()
    for email, subscription_plan_id, payment_method_id, signup_datetime, subscription_expire_datetime in customers:
        hashed_password, first_name, last_name = c.execute('SELECT hashed_password, Person.first_name, Person.last_name FROM Account JOIN Person ON Account.email=Person.email WHERE Account.email=?', (email,)).fetchone()
        data.append({
            "email": email,
            "password": hashed_password,
            "first_name": first_name,
            "last_name": last_name,
            "subscription_plan": c.execute('SELECT name FROM SubscriptionPlan WHERE id=?', (subscription_plan_id,)).fetchone()[0],
            "payment_method": c.execute('SELECT name FROM PaymentMethod WHERE id=?', (payment_method_id,)).fetchone()[0],
            "signup_datetime": signup_datetime,
            "subscription_expire_datetime": subscription_expire_datetime,
            "account_type": "Customer"
        })
        
    employees = c.execute('SELECT email, rank_id, department_id FROM Employee').fetchall()
    for email, rank_id, department_id in employees:
        hashed_password, first_name, last_name = c.execute('SELECT hashed_password, Person.first_name, Person.last_name FROM Account JOIN Person ON Account.email=Person.email WHERE Account.email=?', (email,)).fetchone()
        data.append({
            "email": email,
            "password": hashed_password,
            "first_name": first_name,
            "last_name": last_name,
            "rank": c.execute('SELECT name FROM EmployeeRank WHERE id=?', (rank_id,)).fetchone()[0],
            "department": c.execute('SELECT name FROM EmployeeDepartment WHERE id=?', (department_id,)).fetchone()[0],
            "account_type": "Employee"
        })

    return data, 200


@APP.post('/account/list')
def account_list_post():
    if 'email' not in flask.session or flask.session['account_type'] != 4:
        flask.abort(403)

    return {'message' : 'ok'}, 200 


@APP.post('/account/delete')
def account_delete_post():
    if 'email' not in flask.session or flask.session['account_type'] != 4:
        flask.abort(403)

    email = flask.request.json['email']

    db = get_db()
    c = db.cursor()
    try:
        c.execute('DELETE FROM Account WHERE email=?', (email,))
    except sqlite3.Error as err:
        return {'status': 'failed', 'message' : err.args[0]}, 403
    
    return {'message' : 'ok'}, 200


@APP.route('/chatlog')
def chatlog():
    if 'email' not in flask.session or flask.session['account_type'] != 4:
        flask.abort(403)

    return flask.render_template('chatlog.html')


@APP.get('/chat/log')
def chat_log_get():
    if 'email' not in flask.session or flask.session['account_type'] != 4:
        flask.abort(403)

    db = get_db()
    c = db.cursor()
    
    data = []

    chatlogs = c.execute('SELECT session_id, log_number, datetime, message, email FROM ChatLog').fetchall()
    for session_id, log_number, datetime, message, email in chatlogs:
        data.append({
            "session_id": session_id,
            "log_number": log_number,
            "datetime": datetime,
            "message": message,
            "email": email
        })

    return data, 200


def add_to_chat(session_id, email, message, reply_to=0):
    db = get_db()
    c = db.cursor()
    
    log_number = c.execute('SELECT MAX(log_number) FROM ChatLog WHERE session_id=?', (session_id,)).fetchone()
    if log_number is None:
        flask.abort(404)
    log_number = log_number[0] + 1

    if reply_to == 0 and message.startswith('FORWARD TO OPERATOR:'):
        reply_to = -1
    
    datetime = int(time.time())
    try:
        data = (session_id, log_number, datetime, message, email, reply_to)
        c.execute("""
            INSERT INTO ChatLog (
                session_id,
                log_number,
                datetime,
                message,
                email,
                reply_to
            ) VALUES (?, ?, ?, ?, ?, ?)
        """, data)
    except sqlite3.Error as err:
        return err.args[0]

    return None


def get_ai_chat_contents(session_id):
    db = get_db()
    c = db.cursor()
    
    contents = []
    logs = c.execute('SELECT message, email FROM ChatLog WHERE session_id=? ORDER BY log_number', (session_id,)).fetchall()
    for message, email in logs:
        role = 'model' if email == 'Chatbot' else 'user'
        contents.append({
            'role': role,
            'parts': [{'text': message}]
        })
    return contents


def get_db():
    db = getattr(flask.g, '_database', None)
    if db is None:
        db = flask.g._database = sqlite3.connect(DATABASE, autocommit=True)
    return db


@APP.teardown_appcontext
def close_connection(exception):
    db = getattr(flask.g, '_database', None)
    if db is not None:
        db.close()
