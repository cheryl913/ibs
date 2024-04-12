from flask import Flask, request, render_template, redirect, session, flash, url_for, jsonify
from flask_mysqldb import MySQL
from flask_session import Session
from datetime import datetime, timedelta
from twilio.rest import Client
from geopy.geocoders import Nominatim
import secrets, platform, wmi, pythoncom, random, logging, json
from flask_bcrypt import Bcrypt

import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score
import seaborn as sns
import matplotlib.pyplot as plt
import matplotlib
from flask_mysqldb import MySQL
from config import MYSQL_HOST, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DB, SECRET_KEY
from twilio import ACCOUNT_SID, AUTH_TOKEN

app = Flask(__name__)
 

app.config['MYSQL_HOST'] = MYSQL_HOST
app.config['MYSQL_USER'] = MYSQL_USER
app.config['MYSQL_PASSWORD'] = MYSQL_PASSWORD
app.config['MYSQL_DB'] = MYSQL_DB

mysql = MySQL(app)
bcrypt = Bcrypt(app)
matplotlib.use('Agg')

app.secret_key = SECRET_KEY

app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_FILE_DIR'] = '/tmp/flask_session'
app.config['SESSION_PERMANENT'] = False
app.config['SESSION_USE_SIGNER'] = True
app.config['SESSION_COOKIE_SECURE'] = True
Session(app)

# Twilio
app.twilio['ACCOUNT_SID'] = ACCOUNT_SID
app.twilio['AUTH_TOKEN'] = AUTH_TOKEN
client = Client(ACCOUNT_SID, ACCOUNT_SID)

# Configure logging to a file
logging.basicConfig(filename='server.log', level=logging.DEBUG)

# Initialize Nominatim API
geolocator = Nominatim(user_agent="MyApp")


###    GENERAL    ###

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/index')
def index():
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    session.clear()

    if request.method == 'POST':
        
        username = request.form['username']
        password = request.form['password']
        location = request.form['location']

        cursor = mysql.connection.cursor()

        cursor.execute("""SELECT user_password 
                            FROM user_t 
                            WHERE user_username = %s""", (username,))
        user = cursor.fetchone()

        cursor.close()

        cursor2 = mysql.connection.cursor()

        cursor2.execute("""SELECT admin_password 
                            FROM admin_t 
                            WHERE admin_username = %s""", (username,))
        admin = cursor2.fetchone()

        cursor2.close()

        if user and bcrypt.check_password_hash(user[0], password):
            saved_device = get_user_saved_device(username)
            system_manufacturer = get_system_manufacturer()
            system_model = get_system_model()
            if saved_device == f"{system_manufacturer} {system_model}":
                session['username'] = username
                session['location'] = location
                return redirect('/user_home')
            elif saved_device == '-':
                manufacturer = get_system_manufacturer()
                model = get_system_model()
                
                device_name=manufacturer + ' ' + model    
                cursor = mysql.connection.cursor()
                query = "UPDATE user_t SET user_device = 'Y', user_devicename = %s WHERE user_username = %s"
                cursor.execute(query,(device_name,username))
                mysql.connection.commit()
                cursor.close()
                
                session['username'] = username
                session['location'] = location
                return redirect('/user_home')
            else:
                phoneno = get_user_phone_number(username)
                send_notification(phoneno)
                return '<script>alert("You are on a different device than the one you saved."); window.location.href="/login";</script>'
        elif admin and bcrypt.check_password_hash(admin[0], password):
            session['username'] = username
            return redirect('/admin_home')
        else:
            return '<script>alert("Invalid username or password"); window.location.href="/login";</script>'

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))



###    USER VIEW FUNCTIONS    ###

@app.route('/user_register')
def user_register_init():

    return render_template('user_register.html')

@app.route('/user_register', methods=['GET', 'POST'])
def user_register():
    fname = request.form['fname']
    lname = request.form['lname']
    username = request.form['username']
    password = request.form['password']
    retype_password = request.form['repw']
    twofa = request.form['tfa']
    retype_twofa = request.form['retfa']

    pw_hash = bcrypt.generate_password_hash(password).decode('utf-8')
    twofa_hash = bcrypt.generate_password_hash(twofa).decode('utf-8')

    name = compare_name(fname, lname)
    no_account = compare_account(fname, lname)

    if name:
        if no_account:
            if user_check_username(username):
                if password == retype_password:
                    if twofa == retype_twofa:
                        update_user(username,pw_hash,twofa_hash,fname,lname)
                        return '<script>alert("Your account is registered successfully."); window.location.href="/login";</script>'
                    else:
                        return '<script>alert("Two-Factor Authentication passcodes are not same."); window.location.href="/user_register";</script>'
                else:
                    return '<script>alert("Passwords are not same."); window.location.href="/user_register";</script>'
            else:
                return '<script>alert("Username has been used."); window.location.href="/user_register";</script>'
        else:
            return '<script>alert("You have already owned an account."); window.location.href="/login";</script>'
    else:
        return '<script>alert("Name not found."); window.location.href="/index";</script>'

@app.route('/user_home')
def user_home():
    username = session.get('username')
    location = get_location()
    session['location'] = location
    cursor = mysql.connection.cursor()
    cursor2 = mysql.connection.cursor()
    
    query = """SELECT u.user_id, u.user_username, a.* 
                FROM user_t u 
                INNER JOIN account_t a ON u.user_id = a.acc_uid 
                WHERE u.user_username = %s"""
                
    query2 = """SELECT u2.user_firstname AS beneficiary_firstname, 
                        u2.user_lastname AS beneficiary_lastname, t.*, a1.acc_id  
                FROM transaction_t t 
                JOIN account_t a1 ON t.trans_fromaccount = a1.acc_id
                JOIN account_t a2 ON t.trans_toaccount = a2.acc_id
                JOIN user_t u1 ON a1.acc_uid = u1.user_id
                JOIN user_t u2 ON a2.acc_uid = u2.user_id
                WHERE u1.user_username = %s AND t.trans_status = 'Successful'
                UNION ALL SELECT u2.user_firstname AS beneficiary_firstname, 
                        u2.user_lastname AS beneficiary_lastname, t.*, a1.acc_id 
                FROM transaction_t t 
                JOIN account_t a1 ON t.trans_toaccount = a1.acc_id 
                JOIN account_t a2 ON t.trans_fromaccount = a2.acc_id 
                JOIN user_t u1 ON a1.acc_uid = u1.user_id 
                JOIN user_t u2 ON a2.acc_uid = u2.user_id 
                WHERE u1.user_username = %s AND t.trans_status = 'Successful'"""
    
    cursor.execute(query, (username,))
    cursor2.execute(query2, (username,username))
    
    account = cursor.fetchone()
    records = cursor2.fetchall()
    
    if account is not None:
        acc_no, acc_balance = account[2], account[4]
    
    cursor.close()
    cursor2.close()
    
    if username:
        return render_template('user_home.html', username=username,  active='user_home', acc_no=acc_no, acc_balance=acc_balance, records=records)
    else:
        return '<script>alert("Please login first"); window.location.href="/login";</script>'
    
@app.route('/user_transaction')
def user_transaction():
    username = session.get('username')
    
    acc_no, acc_balance, acc_type = get_account(username)
        
    if username:
        return render_template('user_transaction.html', username=username, active='user_transaction', acc_no=acc_no, acc_balance=acc_balance,acc_type=acc_type)
    else:
        return '<script>alert("Please login first"); window.location.href="/login";</script>'
    
@app.route('/user_transfer')
def user_transfer_init():
    username = session.get('username')
    
    cursor = mysql.connection.cursor()
    query = """SELECT u.user_username, a.acc_id 
                FROM user_t u 
                JOIN account_t a ON u.user_id = a.acc_uid 
                WHERE u.user_username = %s"""
    cursor.execute(query, (username,))
    account = cursor.fetchone()
    
    cursor2 = mysql.connection.cursor()
    query2 = """SELECT u2.user_firstname AS beneficiary_firstname, 
                        u2.user_lastname AS beneficiary_lastname, 
                        f.favo_accno, f.favo_nickname 
                FROM favourite_account_t f 
                JOIN account_t a ON f.favo_accno = a.acc_id 
                JOIN user_t u1 ON u1.user_id = f.favo_uid 
                JOIN user_t u2 ON a.acc_uid = u2.user_id 
                WHERE u1.user_username = %s AND u2.user_username <> %s;"""
    cursor2.execute(query2, (username,username))
    favoacc = cursor2.fetchall()
    
    if account is not None:
        acc_no = account[1]

    if username:
        return render_template('user_transfer.html', username=username, active='user_transaction', acc_no=acc_no, favoacc=favoacc)
    else:
        return '<script>alert("Please login first"); window.location.href="/login";</script>'    
    

@app.route('/user_transfer', methods=['GET', 'POST'])
def user_transfer():
    username = session.get('username')
    location = session.get('location')
    
    from_account = request.form['from_account']
    to_account = request.form['to_account']
    amount = request.form['amount']
    reference = request.form['reference']
    favorite_name = request.form['name']
    date = datetime.now()

    cursor = mysql.connection.cursor()
    
    if to_account == 'favorite':
        favorite_account = request.form['accno']
        to_account_no = favorite_account
        to_account_name = favorite_name
        
        query = """INSERT INTO transaction_t 
                    (trans_fromaccount, trans_datetime, trans_location, trans_description, trans_amount, 
                        trans_toaccount, trans_tac, trans_status, trans_fraud) 
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"""
                    
        cursor.execute(query,(from_account,date,location,reference,amount,to_account_no,None,"Created",0))
        
        # Send TAC to user's WhatsApp
        phone_number = get_user_phone_number(username)  # Retrieve user's phone number from database
        send_tac_to_whatsapp(phone_number,username)
        
        session['from_account'] = from_account
        session['amount'] = amount
        session['reference'] = reference
        session['to_account_no'] = to_account_no
        session['to_account_name'] = to_account_name
        
        return redirect(url_for('user_checktac_init'))
        
    elif to_account == 'new':
        new_account = request.form['new_account']
        to_account_no = new_account 

        cursor1 = mysql.connection.cursor()
        query1 = """SELECT u.user_firstname, u.user_lastname 
                FROM user_t u 
                JOIN account_t a
                ON u.user_id = a.acc_uid
                WHERE a.acc_id = %s"""
        cursor1.execute(query1,(to_account_no,))
        name = cursor1.fetchone()
        cursor1.close()

        if name is not None:
            if to_account_no == from_account:
                return '<script>alert("You are not allowed to make a transaction to own account."); window.location.href="/user_transfer";</script>'
            else:
                fname, lname = name[0], name[1]
                to_account_name = f"{fname} {lname}"
                query2 = """INSERT INTO transaction_t 
                            (trans_fromaccount, trans_datetime, trans_location, trans_description, trans_amount, 
                            trans_toaccount, trans_tac, trans_status, trans_fraud) 
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"""
                        
                cursor.execute(query2,(from_account,date,location,reference,amount,to_account_no,None,"Created",0))
                
                cursor.close()

                phone_number = get_user_phone_number(username)
                send_tac_to_whatsapp(phone_number,username)
                
                session['from_account'] = from_account
                session['amount'] = amount
                session['reference'] = reference
                session['to_account_no'] = to_account_no
                session['to_account_name'] = to_account_name
                
                return redirect(url_for('user_checktac_init'))
        else:
            return '<script>alert("Account not found, Ensure the account number is correct!"); window.location.href="/user_transfer";</script>'
    else:
        return '<script>alert("Something went wrong, please try again!"); window.location.href="/user_transfer";</script>'
    
        
@app.route('/user_checktac')
def user_checktac_init():
    username = session.get('username')  
    
    from_account = session.get('from_account')
    amount = session.get('amount')
    reference = session.get('reference')
    to_account_no = session.get('to_account_no')
    to_account_name = session.get('to_account_name')

    return render_template('user_checktac.html', username=username, active='user_transaction', from_account=from_account, amount=amount, reference=reference, to_account_no=to_account_no, to_account_name=to_account_name)

@app.route('/user_checktac', methods=['GET', 'POST'])
def user_checktac():
    username = session.get('username')
    
    tac = request.form['tac']
    phone_number = get_user_phone_number(username)
    session['phone_number'] = phone_number
    session['tac'] = tac
    
    # Check if TAC are the same
    if check_tac(tac):
        return redirect(url_for('user_verify'))
    
    else:
        show_alert = True
        
        from_account = session.get('from_account')
        amount = session.get('amount')
        reference = session.get('reference')
        to_account_no = session.get('to_account_no')
        to_account_name = session.get('to_account_name')
        
        send_tac_to_whatsapp(phone_number,username)
        flash('TAC incorrect!')
        return render_template('user_checktac.html', username=username, active='user_transaction', alert_type='alert-warning',from_account=from_account, amount=amount, reference=reference, to_account_no=to_account_no, to_account_name=to_account_name, show_alert=show_alert)


@app.route('/user_verify', methods=['GET', 'POST'])
def user_verify():
    username = session.get('username')
    
    amount = get_amount(username)
    to_account_no = get_toaccount(username)
        
    # Compare devices
    saved_device = get_user_saved_device(username)  # Retrieve user's saved device from database
    system_manufacturer = get_system_manufacturer()  # Get the user's system manufacturer
    system_model = get_system_model()  # Get the user's system model
        
    if saved_device == f"{system_manufacturer} {system_model}":
        # Transaction successful
        transaction_success(username)
        update_balance(username,amount)
        update_tobalance(to_account_no,amount)            
        acc_no, acc_balance, acc_type = get_account(username)
        flash("Transaction successful!")
        return render_template("user_transaction.html", alert_type='alert-success',username=username,acc_no=acc_no,acc_balance=acc_balance,acc_type=acc_type)
    else:
        # Transaction failed due to device mismatch
        transaction_failed(username)
        acc_no, acc_balance, acc_type = get_account(username)
        flash("Device mismatch. \nTransaction failed!")
        return render_template("user_transaction.html", alert_type='alert-danger',username=username,acc_no=acc_no,acc_balance=acc_balance,acc_type=acc_type)


@app.route('/user_favourite')
def user_favourite():
    # Retrieve username from session
    username = session.get('username')
    
    cursor = mysql.connection.cursor()
    
    query = """SELECT u2.user_firstname AS beneficiary_firstname, 
                        u2.user_lastname AS beneficiary_lastname, 
                        f.favo_accno, f.favo_nickname 
                FROM favourite_account_t f 
                JOIN account_t a ON f.favo_accno = a.acc_id 
                JOIN user_t u1 ON u1.user_id = f.favo_uid 
                JOIN user_t u2 ON a.acc_uid = u2.user_id 
                WHERE u1.user_username = %s 
                AND u2.user_username <> %s;"""
    
    cursor.execute(query, (username,username))
    favoacc = cursor.fetchall()
    
    cursor.close()
    
    if username:
        return render_template('user_favourite.html', username=username, active='user_transaction', favoacc=favoacc)
    else:
        # Show alert box if user is not logged in
        return '<script>alert("Please login first"); window.location.href="/login";</script>'

@app.route('/user_addfavourite', methods=['POST'])
def user_addfavourite():
    username = session.get('username')

    userid = get_userid(username)
    
    favonickname = request.form['favoname']
    favoacc = request.form['accno']
    
    if username:
        if compare_favoaccount(favoacc):
            if check_favoaccount(userid,favoacc):
                cursor = mysql.connection.cursor()
                query = """INSERT INTO favourite_account_t (favo_uid, favo_accno, favo_nickname)
                            VALUES (%s, %s, %s)"""
                
                cursor.execute(query, (userid,favoacc,favonickname))
                
                cursor.close()
                
                return redirect(url_for('user_favourite'))
            else:
                return '<script>alert("This account is already your favourite account."); window.location.href="/user_favourite";</script>'
        else:
            return '<script>alert("Account number not found."); window.location.href="/user_favourite";</script>'
    
    else:
        # Show alert box if user is not logged in
        return '<script>alert("Please login first"); window.location.href="/login";</script>'


@app.route('/user_deletefavourite', methods=['POST'])
def user_deletefavourite():
    username = session.get('username')
    accid = request.form['accid']

    userid = get_userid(username)

    cursor = mysql.connection.cursor()

    query = """DELETE FROM favourite_account_t WHERE favo_accno = %s AND favo_uid = %s"""

    cursor.execute(query,(accid,userid))
    mysql.connection.commit()
    cursor.close()
    return redirect(url_for('user_favourite'))


@app.route('/user_favourite', methods=['GET', 'POST'])
def update_favourite():
    # Retrieve username from session
    username = session.get('username')
    
    cursor = mysql.connection.cursor()
    
    new_nickname = request.form['new_nickname']
    account_number = request.form['accid']
    
    query = """UPDATE favourite_account_t f
                JOIN account_t a ON f.favo_accno = a.acc_id 
                JOIN user_t u1 ON u1.user_id = f.favo_uid 
                JOIN user_t u2 ON a.acc_uid = u2.user_id
                SET f.favo_nickname = %s
                WHERE u1.user_username = %s
                AND f.favo_accno = %s;"""
    
    cursor.execute(query, (new_nickname,username,account_number))
    
    cursor.close()
    
    if username:
        return redirect(url_for('user_favourite'))
    else:
        # Show alert box if user is not logged in
        return '<script>alert("Please login first"); window.location.href="/login";</script>'
        
@app.route('/user_device', methods=['GET', 'POST'])
def user_device():
    # Retrieve username from session
    username = session.get('username')
    
    system_name = platform.system()
    
    cursor = mysql.connection.cursor()
    query = 'SELECT user_devicename FROM user_t WHERE user_username = %s'
    cursor.execute(query, (username,))
    device = cursor.fetchone()
        
    if request.method == 'POST':
        tfa = request.form['tfa']
        if bcrypt.check_password_hash(get_2fa(username), tfa):
            if system_name == 'Windows':
                manufacturer = get_system_manufacturer()
                model = get_system_model()
                
                device_name=manufacturer + ' ' + model    
                cursor = mysql.connection.cursor()
                query = "UPDATE user_t SET user_device = 'Y', user_devicename = %s WHERE user_username = %s"
                cursor.execute(query,(device_name,username))
                mysql.connection.commit()
                cursor.close()

                return '<script>alert("Your device has been changed."); window.location.href="/user_device";</script>'
            else:            
                return '<script>alert("You are not using a Windows PC device!"); window.location.href="/user_device";</script>'
        else:
            return '<script>alert("Incorrect two-factor authentication!"); window.location.href="/user_device";</script>'

    if device is not None:
        devicename = device[0]

    if username:
        return render_template('user_device.html', devicename=devicename)
    else:
        # Show alert box if user is not logged in
        return '<script>alert("Please login first"); window.location.href="/login";</script>'

@app.route('/user_changepassword', methods=['GET', 'POST'])
def user_changepassword():
    username = session.get('username')

    if username:
        if request.method == 'POST':
            oldpw = request.form['old']
            newpw = request.form['new']
            confirmnew = request.form['confirmnew']
            date = datetime.now()

            pw_hash = bcrypt.generate_password_hash(newpw).decode('utf-8')
            
            cursor = mysql.connection.cursor()
            query = """SELECT user_password FROM user_t WHERE user_username=%s"""
            cursor.execute(query,(username,))
            password = cursor.fetchone()
            cursor.close()

            if newpw == confirmnew:
                if bcrypt.check_password_hash(password[0], oldpw):
                    update_password(pw_hash,date,username)
                else:
                    return '<script>alert("Incorrect old password"); window.location.href="/user_changepassword";</script>'
            else:
                return '<script>alert("New password and confirm new password do not match."); window.location.href="/user_changepassword";</script>'
            
            return '<script>alert("Password changed."); window.location.href="/user_changepassword";</script>'
        
        return render_template('user_changepassword.html', username=username, active='user_changepassword')
    else:
        # Show alert box if user is not logged in
        return '<script>alert("Please login first"); window.location.href="/login";</script>'

@app.route('/user_change2fa', methods=['GET', 'POST'])
def user_change2fa():
    username = session.get('username')

    if username:
        if request.method == 'POST':
            oldtfa = request.form['oldtfa']
            newtfa = request.form['newtfa']
            confirmtfa = request.form['confirmtfa']

            tfa_hash = bcrypt.generate_password_hash(newtfa).decode('utf-8')
            
            cursor = mysql.connection.cursor()
            query = """SELECT user_2fa FROM user_t WHERE user_username=%s"""
            cursor.execute(query,(username,))
            tfa = cursor.fetchone()
            cursor.close()

            if newtfa == confirmtfa:
                if bcrypt.check_password_hash(tfa[0], oldtfa):
                    update_2fa(tfa_hash,username)
                else:
                    return '<script>alert("Incorrect old two-factor authentication."); window.location.href="/user_changepassword";</script>'
            else:
                return '<script>alert("New 2FA and confirm new 2FA do not match."); window.location.href="/user_changepassword";</script>'
            
            return '<script>alert("2FA changed."); window.location.href="/user_changepassword";</script>'
        
        return render_template('user_changepassword.html', username=username, active='user_changepassword')
    else:
        # Show alert box if user is not logged in
        return '<script>alert("Please login first"); window.location.href="/login";</script>'
    

###     USER FUNCTIONS    ###

def compare_name(fname, lname):
    cursor = mysql.connection.cursor()
    query = 'SELECT user_firstname, user_lastname FROM user_t WHERE user_firstname = %s AND user_lastname = %s'
    cursor.execute(query,(fname,lname))
    user = cursor.fetchone()
    cursor.close()
    if user is not None:
        return True
    else:
        return False
    
def compare_account(fname,lname):
    cursor = mysql.connection.cursor()
    query = 'SELECT user_account FROM user_t WHERE user_firstname = %s AND user_lastname = %s'
    cursor.execute(query,(fname,lname))
    user = cursor.fetchone()
    cursor.close()

    if user is not None:
        account_YN = user[0]
    
    if account_YN == 'N':
        return True
    else:
        return False
    
def compare_favoaccount(accno):
    cursor = mysql.connection.cursor()
    query = 'SELECT acc_id FROM account_t WHERE acc_id = %s'
    cursor.execute(query,(accno,))
    account = cursor.fetchone()
    cursor.close()

    if account is not None:
        return True
    else:
        return False
    
def check_favoaccount(userid,accno):
    cursor = mysql.connection.cursor()
    query = 'SELECT favo_uid, favo_accno FROM favourite_account_t WHERE favo_uid = %s AND favo_accno = %s'
    cursor.execute(query,(userid,accno))
    account = cursor.fetchone()
    cursor.close()

    if account is None:
        return True
    else:
        return False
    
def user_check_username(username):
    cursor = mysql.connection.cursor()
    query = """SELECT user_username FROM user_t WHERE user_username = %s"""
    cursor.execute(query,(username,))
    uid = cursor.fetchone()

    if uid is None:
        return True
    else:
        return False

    
def update_user(username,password,twofa,fname,lname):
    cursor = mysql.connection.cursor()
    query = """UPDATE user_t 
                SET user_account = %s, user_username = %s, user_password = %s,
                user_2fa = %s WHERE user_firstname = %s AND user_lastname = %s"""
    cursor.execute(query,('Y',username,password,twofa,fname,lname))
    mysql.connection.commit()
    cursor.close()    


def get_user_phone_number(username):
    cursor = mysql.connection.cursor()
    query = 'SELECT user_phonenum FROM user_t WHERE user_username = %s'
    cursor.execute(query,(username,))
    phonenum = cursor.fetchone()
    
    if phonenum is not None:
        phoneno = phonenum[0]
    
    return '+6' + phoneno

def send_notification(phone_number):
    # Send the TAC to the user's WhatsApp
    client.messages.create(
        from_='whatsapp:+14155238886',
        body='IBS: Your account was found to have *suspicious login* using non-saved device! Change your password immediately if it is not you.',
        to='whatsapp:' + phone_number
    )

def send_tac_to_whatsapp(phone_number,username):
    # Generate a 6-digit random number as TAC
    tac = str(random.randint(100000, 999999))
    
    cursor = mysql.connection.cursor()
    
    query = """UPDATE transaction_t t 
                JOIN (SELECT a.acc_id, u.user_username FROM account_t a 
                        JOIN user_t u ON a.acc_uid = u.user_id 
                        WHERE u.user_username = %s) au 
                ON t.trans_fromaccount = au.acc_id 
                SET t.trans_tac = %s WHERE au.user_username = %s 
                AND t.trans_id = (SELECT MAX(trans_id) FROM transaction_t)"""
                
    cursor.execute(query,(username,tac,username))
    
    # Send the TAC to the user's WhatsApp
    client.messages.create(
        from_='whatsapp:+14155238886',
        body='IBS: Your TAC requested is ' + tac + '. *NEVER SHARE YOUR OTP!*',
        to='whatsapp:' + phone_number
    )

def get_account(username):
    cursor = mysql.connection.cursor()
    
    query = """SELECT u.user_id, u.user_username, a.* FROM user_t u 
                INNER JOIN account_t a ON u.user_id = a.acc_uid 
                WHERE u.user_username = %s"""
    
    cursor.execute(query, (username,))
    account = cursor.fetchone()
    
    if account is not None:
        acc_no, acc_balance, acc_type = account[2], account[4], account[5]
    
    return acc_no, acc_balance, acc_type

def check_tac(tac):
    expected_tac = get_tac()
    
    if tac is not None:
        if str(tac) == str(expected_tac):
            return True
    
    return False

def get_tac():
    username = session.get('username')
    # Retrieve the expected TAC from database
    cursor = mysql.connection.cursor()
    
    query = """SELECT t.trans_tac FROM transaction_t t 
                JOIN (SELECT a.acc_id, u.user_username FROM account_t a 
                        JOIN user_t u ON a.acc_uid = u.user_id 
                        WHERE u.user_username = %s) au 
                ON t.trans_fromaccount = au.acc_id 
                WHERE au.user_username = %s 
                AND t.trans_id = (SELECT MAX(trans_id) FROM transaction_t);"""
                
    cursor.execute(query,(username,username))
    expected_tac = cursor.fetchone()
    
    if expected_tac is not None:
        tac = expected_tac[0]
    
    return tac

def get_user_saved_device(username):
    # Retrieve and return the user's saved device from the database
    cursor = mysql.connection.cursor()
    query = 'SELECT user_devicename FROM user_t WHERE user_username = %s'
    cursor.execute(query,(username,))
    saved_device = cursor.fetchone()
    
    saved = None
    
    if saved_device is not None:
        saved = saved_device[0]
    
    return saved

def get_system_manufacturer():
    # Get and return the user's system manufacturer
    pythoncom.CoInitialize()
    
    c = wmi.WMI()
    system_info = c.Win32_ComputerSystem()[0]
    manufacturer = system_info.Manufacturer
    
    return manufacturer

def get_system_model():
    # Get and return the user's system model
    pythoncom.CoInitialize()
    
    c = wmi.WMI()
    system_info = c.Win32_ComputerSystem()[0]
    model = system_info.Model
    
    return model

def get_2fa(username):
    cursor = mysql.connection.cursor()
    query = """SELECT user_2fa FROM user_t WHERE user_username = %s"""
    cursor.execute(query,(username,))
    tfa = cursor.fetchone()
    cursor.close()

    if tfa is not None:
        return tfa[0]

def transaction_success(username):
    # Perform the transaction
    cursor = mysql.connection.cursor()
    
    query = """UPDATE transaction_t t 
                JOIN (SELECT a.acc_id, u.user_username FROM account_t a 
                        JOIN user_t u ON a.acc_uid = u.user_id 
                        WHERE u.user_username = %s) au 
                ON t.trans_fromaccount = au.acc_id 
                SET t.trans_tac = NULL, t.trans_status = "Successful" 
                WHERE au.user_username = %s 
                AND t.trans_id = (SELECT MAX(trans_id) FROM transaction_t)"""

    cursor.execute(query,(username,username))
    
    cursor.close()

def check_balance(username):
    cursor = mysql.connection.cursor()
    query = """SELECT a.acc_balance FROM user_t u 
                INNER JOIN account_t a ON u.user_id = a.acc_uid 
                WHERE u.user_username = %s"""
    cursor.execute(query,(username,))
    acc_balance = cursor.fetchone()
    
    balance = None
    
    if acc_balance is not None:
        balance = acc_balance[0]
    
    return balance

def update_balance(username, amount):
    cursor = mysql.connection.cursor()

    query = """UPDATE account_t a
                    JOIN user_t u
                    ON a.acc_uid = u.user_id 
                    SET a.acc_balance = a.acc_balance - %s
                    WHERE u.user_username = %s;"""
    
    new_balance = cursor.execute(query,(amount,username))
    mysql.connection.commit() 
    cursor.close()

    return new_balance

def update_tobalance(toaccount, amount):
    cursor = mysql.connection.cursor()
    
    query = """UPDATE account_t 
                    SET acc_balance = acc_balance + %s
                    WHERE acc_id = %s;"""
    
    new_tobalance = cursor.execute(query,(amount,toaccount))
    mysql.connection.commit() 
    cursor.close()

    return new_tobalance

def transaction_failed(username):
    # Perform the transaction
    cursor = mysql.connection.cursor()
    
    query = """UPDATE transaction_t t 
                JOIN (SELECT a.acc_id, u.user_username FROM account_t a 
                        JOIN user_t u ON a.acc_uid = u.user_id 
                        WHERE u.user_username = %s) au 
                ON t.trans_fromaccount = au.acc_id 
                SET t.trans_tac = NULL, t.trans_status = "Failed" 
                WHERE au.user_username = %s 
                AND t.trans_id = t.trans_id = (SELECT MAX(trans_id) FROM transaction_t)"""
                
    cursor.execute(query,(username,username))


def get_userid(username):
    cursor = mysql.connection.cursor()
    query = """SELECT user_id FROM user_t WHERE user_username = %s"""
    cursor.execute(query, (username,))
    user = cursor.fetchone()
    
    userid = None
    
    if user is not None:
        userid = user[0]
    
    return userid

def get_amount(username):
    cursor = mysql.connection.cursor()
    query = """SELECT t.trans_amount FROM transaction_t t 
                JOIN (SELECT a.acc_id, u.user_username FROM account_t a 
                        JOIN user_t u ON a.acc_uid = u.user_id 
                        WHERE u.user_username = %s) au 
                ON t.trans_fromaccount = au.acc_id 
                WHERE au.user_username = %s 
                AND t.trans_id = (SELECT MAX(trans_id) FROM transaction_t);"""
    cursor.execute(query, (username,username))
    data = cursor.fetchone()
    
    if data is not None:
        amount = data[0]
    
    return amount

def get_toaccount(username):    
    cursor = mysql.connection.cursor()
    query = """SELECT t.trans_toaccount FROM transaction_t t 
                JOIN (SELECT a.acc_id, u.user_username FROM account_t a 
                        JOIN user_t u ON a.acc_uid = u.user_id 
                        WHERE u.user_username = %s) au 
                ON t.trans_fromaccount = au.acc_id 
                WHERE au.user_username = %s 
                AND t.trans_id = (SELECT MAX(trans_id) FROM transaction_t);"""
    cursor.execute(query, (username,username))
    data = cursor.fetchone()
    
    if data is not None:
        to_account_no = data[0]
    
    return to_account_no

def update_password(newpw,date,username):
    cursor = mysql.connection.cursor()

    query = """UPDATE user_t SET user_password = %s, user_changepwdate = %s
                WHERE user_username = %s"""

    cursor.execute(query,(newpw,date,username))
    mysql.connection.commit()
    cursor.close()

def update_2fa(newtfa,username):
    cursor = mysql.connection.cursor()

    query = """UPDATE user_t SET user_2fa = %s WHERE user_username = %s"""

    cursor.execute(query,(newtfa,username))
    mysql.connection.commit()
    cursor.close()

def get_location():
    location_data = session.get('location')

    if location_data:
        # If location data is found, return the actual location directly
        return location_data
    else:
        # Parse the location data from the session
        location_data = json.loads(session.get('location'))

        latitude = location_data['latitude']
        longitude = location_data['longitude']

        coordinates = (latitude, longitude)

        location = geolocator.reverse(coordinates)

        address = location.raw['address']

        # Traverse the data
        city = address.get('city', '')
        country = address.get('country', '')

        actual_location = city + ', ' + country
        
        return actual_location



###    ADMIN VIEW FUNCTIONS    ###


@app.route('/admin_home')
def admin_home():
    username = session.get('username')

    cursor = mysql.connection.cursor()
    
    query = """SELECT
                COUNT(*) AS total_transactions,
                SUM(CASE WHEN trans_status = 'Successful' THEN 1 ELSE 0 END) AS successful_transactions,
                SUM(CASE WHEN trans_status = 'Failed' THEN 1 ELSE 0 END) AS failed_transactions,
                SUM(trans_fraud) AS fraudulent_transactions
                FROM transaction_t; """
    
    cursor.execute(query)
    count = cursor.fetchone()
    cursor.close()

    total, success, fail, fraud = count[0], count[1], count[2], count[3]

    if username:
        return render_template('admin_home.html', username=username, active='admin_home', total=total, success=success, fail=fail, fraud=fraud)
    else:
        return '<script>alert("Please login first"); window.location.href="/login";</script>'
    

@app.route('/admin_fraud')
def admin_fraud():
    username = session.get('username')

    # Call the perform_fraud_detection() function
    fraud_prediction, data_html = perform_fraud_detection()

    if username:
        return render_template('admin_fraud.html', fraud_prediction=fraud_prediction, data_html=data_html)
    else:
        return '<script>alert("Please login first"); window.location.href="/login";</script>'


@app.route('/admin_register')
def admin_register():
    username = session.get('username')
    if username:
        return render_template('admin_register.html',username=username, active='admin_register')
    else:
        return '<script>alert("Please login first"); window.location.href="/login";</script>'  
    

@app.route('/admin_create_user', methods=['GET', 'POST'])
def admin_create_user():
    username = session.get('username')

    if username:
        if request.method == 'POST':
            fname = request.form['fname']
            lname = request.form['lname']
            email = request.form['email']
            phoneno = request.form['phoneno']
            dob = request.form['dob']
            gender = request.form['gender']
            street = request.form['street']
            city = request.form['city']
            state = request.form['state']
            postcode = request.form['postcode']
            country = request.form['country']

            if not compare_name(fname,lname):
                cursor = mysql.connection.cursor()
                query = """INSERT INTO user_t (
                            user_firstname,
                            user_lastname,
                            user_gender,
                            user_dob,
                            user_street,	
                            user_city,
                            user_state,	
                            user_postcode,	
                            user_country,	
                            user_phonenum,	
                            user_email,
                            user_account,	
                            user_username,	
                            user_password,	
                            user_device,
                            user_devicename,	
                            user_roleid)
                            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"""
                cursor.execute(query,(fname,lname,gender,dob,street,city,state,postcode,country,phoneno,email,'N','-','-','N','-','2'))
                mysql.connection.commit()
                cursor.close()

                create_account()

                flash('Record has been created.')
                return render_template('admin_register.html',username=username,alert_type='alert-success')
            else:
                flash('Record exists.')
                return render_template('admin_register.html',username=username,alert_type="alert-warning")
            
        return render_template('admin_create_user.html',username=username,active='admin_register')
    else:
        return '<script>alert("Please login first"); window.location.href="/login";</script>'


@app.route('/admin_create_admin', methods=['GET', 'POST'])
def admin_create_admin():
    username = session.get('username')

    if username:
        if request.method == 'POST':
            username = request.form['username']
            password = request.form['password']
            confirm_password = request.form['con_password']

            pw_hash = bcrypt.generate_password_hash(password).decode('utf-8')

            if check_username(username):
                if password == confirm_password:
                    cursor = mysql.connection.cursor()
                    query = """INSERT INTO admin_t (admin_username,admin_password,admin_roleid)
                                VALUES (%s,%s,%s)"""
                    cursor.execute(query,(username,pw_hash,"1"))
                    mysql.connection.commit()
                    cursor.close()

                    flash('Record has been created.')
                    return render_template('admin_register.html',username=username,alert_type='alert-success')
                else:
                    return '<script>alert("Password are not same."); window.location.href="/admin_create_admin";</script>'
            else:
                return '<script>alert("Username has been used."); window.location.href="/admin_create_admin";</script>'

        return render_template('admin_create_admin.html',username=username,active='admin_register')
    else:
        return '<script>alert("Please login first"); window.location.href="/login";</script>'
    

@app.route('/admin_checkuser', methods=['GET', 'POST'])
def admin_checkuser():
    username = session.get('username')
    
    cursor = mysql.connection.cursor()
    
    query = """SELECT user_firstname, user_lastname, user_username, user_changepwdate, user_phonenum
                FROM user_t WHERE user_account = 'Y'"""
    
    cursor.execute(query)
    users = cursor.fetchall()
    
    cursor.close()

    if request.method == 'POST':
        send_change_password_message()
        
    if username:
        return render_template('admin_checkuser.html', username=username, active='admin_checkuser', users=users)
    else:
        # Show alert box if user is not logged in
        return '<script>alert("Please login first"); window.location.href="/login";</script>'


###    ADMIN FUNCTIONS    ###

def get_newCreatedAccount():
    cursor = mysql.connection.cursor()
    query = """SELECT MAX(user_id) FROM user_t"""
    cursor.execute(query)
    uid = cursor.fetchone()

    if uid is not None:
        id = uid[0]
    
    return id

def create_account():
    id = get_newCreatedAccount()
    account_type = random.choice(['savings', 'current'])

    cursor = mysql.connection.cursor()
    query = """INSERT INTO account_t (acc_uid,acc_balance,acc_type) VALUES (%s,%s,%s)"""
    cursor.execute(query,(id,'200.00',account_type))
    mysql.connection.commit()
    cursor.close()

def check_username(username):
    cursor = mysql.connection.cursor()
    query = """SELECT admin_username FROM admin_t WHERE admin_username = %s"""
    cursor.execute(query,(username,))
    uid = cursor.fetchone()

    if uid is None:
        return True
    else:
        return False
    
def send_change_password_message():
    three_months_ago = datetime.now() - timedelta(days=90)

    cursor = mysql.connection.cursor()
    query = """SELECT * FROM user_t WHERE user_changepwdate <= %s"""
    cursor.execute(query,(three_months_ago,))
    users = cursor.fetchall()
    cursor.close()

    for user in users:
        # Send a WhatsApp message to each user
        client.messages.create(
            body='IBS: Your password was last changed 3 months ago. Please consider changing it.',
            from_='whatsapp:+14155238886',
            to='whatsapp:' + '+6' + str(user[10])
        )


###    MACHINE LEARNING    ###
def perform_fraud_detection():
    # Load the dataset
    existing_data = pd.read_csv('transaction_data.csv')
    
    next_id = existing_data['Transaction ID'].max() + 1
    all_locations = existing_data['Location'].unique()

    # Convert 'Transaction Date' to Unix timestamp
    existing_data['Transaction Date'] = pd.to_datetime(existing_data['Transaction Date']).astype('int64') // 10**9

    # Split the data into features (X) and labels (y)
    X = existing_data.drop('Fraud Label', axis=1)
    y = existing_data['Fraud Label']

    # Perform one-hot encoding for categorical variables
    categorical_columns = ['Transaction Type', 'Merchant', 'Location', 'Transaction Status']
    X_encoded = pd.get_dummies(X[categorical_columns])

    # Convert the encoded data back to a DataFrame
    X = pd.concat([X.drop(categorical_columns, axis=1), X_encoded], axis=1)

    # Split the data into training and testing sets
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    # Create the random forest classifier
    clf = RandomForestClassifier()

    # Train the classifier
    clf.fit(X_train, y_train)

    # Make predictions on the test set
    y_pred = clf.predict(X_test)

    # Evaluate the model
    accuracy = accuracy_score(y_test, y_pred)
    print(f'Accuracy: {accuracy}')

    # Prepare feature names for the new transaction
    new_transaction_columns = X.columns.tolist()

    cursor = mysql.connection.cursor()
    cursor.execute("""SELECT u.user_id, t.trans_id, t.trans_datetime, t.trans_location,
                      t.trans_amount, t.trans_status
                        FROM transaction_t t 
                        JOIN account_t a
                        ON t.trans_fromaccount = a.acc_id
                        JOIN user_t u 
                        ON a.acc_uid = u.user_id
                        WHERE t.trans_id = (SELECT MAX(trans_id) 
                                            FROM transaction_t
                                            WHERE trans_status = 'Successful' 
                                            AND trans_processed = FALSE)""")
    fetch_data = cursor.fetchall()

    # Predict the fraud label for a new transaction
    # Check if data is fetched and cursor.description is not None
    if fetch_data and cursor.description:
        # Convert the data into a DataFrame
        fetch_data = pd.DataFrame(fetch_data, columns=[i[0] for i in cursor.description])

        cursor.close()

        # Fetch data from the DataFrame
        amount = fetch_data['trans_amount'].iloc[-1]
        date = pd.to_datetime(fetch_data['trans_datetime']).astype('int64') // 10**9
        status = fetch_data['trans_status'].iloc[-1]
        uid = fetch_data['user_id'].iloc[-1]
        trans_location = fetch_data['trans_location'].iloc[-1]
        trans_type = 'Online Transfer'
        merchant = 'IBS'

        new_transaction = {
            'Transaction ID': next_id,
            'Transaction Amount': amount,
            'Transaction Date': date,
            'Transaction Status_Successful': 1 if status == 'Successful' else 0,
            'Transaction Type_Online Transfer': 1 if trans_type == 'Online Transfer' else 0,
            'Merchant_IBS': 1 if merchant == 'IBS' else 0,
            'Customer ID': uid,
            **{f'Location_{location}': 1 if trans_location == location else 0 for location in all_locations},
            'Location_Other': 1 if trans_location not in all_locations else 0
        }

        # Reorder the columns to match the feature names used during training
        new_transaction = {key: new_transaction[key] for key in new_transaction_columns if key in new_transaction}

        new_transaction_new = pd.DataFrame([new_transaction], columns=new_transaction.keys())
        fraud_prediction = clf.predict(new_transaction_new)
        print(f'Fraud Prediction: {fraud_prediction}')

        cursor2 = mysql.connection.cursor()
        cursor2.execute("""UPDATE transaction_t
                            SET trans_fraud = %s, trans_processed = TRUE
                            WHERE trans_status='Successful'
                            AND trans_processed = FALSE""", (fraud_prediction,))
        cursor2.close()

        # Add the fraud label to the new transaction
        new_transaction_new['Fraud Label'] = fraud_prediction[0]

        # Reverse one-hot encoding for the new transaction
        new_transaction_new['Transaction Type'] = (new_transaction_new[[col for col in new_transaction_new 
                                                    if col.startswith('Transaction Type_')]]
                                                      .idxmax(axis=1).str.replace('Transaction Type_', ''))
        new_transaction_new['Merchant'] = (new_transaction_new[[col for col in new_transaction_new 
                                            if col.startswith('Merchant_')]]
                                              .idxmax(axis=1).str.replace('Merchant_', ''))
        new_transaction_new['Location'] = (new_transaction_new[[col for col in new_transaction_new 
                                            if col.startswith('Location_')]]
                                              .idxmax(axis=1).str.replace('Location_', ''))
        new_transaction_new['Transaction Status'] = (new_transaction_new[[col for col in new_transaction_new 
                                                      if col.startswith('Transaction Status_')]]
                                                        .idxmax(axis=1).str.replace('Transaction Status_', ''))
        
        # Convert to datetime
        new_transaction_new['Transaction Date'] = new_transaction_new['Transaction Date'].values.flatten()[0]

        # Drop the one-hot encoded columns from the new transaction
        new_transaction_new = (new_transaction_new[['Transaction ID', 'Transaction Amount', 'Transaction Date', 
                                                    'Transaction Type', 'Customer ID', 'Merchant', 'Location', 
                                                    'Transaction Status', 'Fraud Label']])

        # Append the new transaction to the original DataFrame
        existing_data = pd.concat([existing_data, new_transaction_new], ignore_index=True)

        # Convert 'Transaction Date' to datetime format
        existing_data['Transaction Date'] = pd.to_datetime(existing_data['Transaction Date'], unit='s')

        # Write the DataFrame back to the .csv file
        existing_data.to_csv('transaction_data.csv', index=False)

        # Count the occurrences of each fraud label
        fraud_counts = existing_data['Fraud Label'].value_counts()

        # Create a bar plot
        sns.barplot(x=fraud_counts.index, y=fraud_counts.values)
        plt.xlabel('Fraud Label')
        plt.ylabel('Count')
        plt.title('Fraud Label Distribution')
        plt.savefig('plot.png')
        data_html = existing_data.to_html()

        return fraud_prediction, data_html

    else:
        print("No data fetched from the database or cursor.description is None.")
        existing_data['Transaction Date'] = pd.to_datetime(existing_data['Transaction Date'], unit='s')
        # Return all the existing data
        data_html = existing_data.to_html()
        return None, data_html

    
    
if __name__ == '__main__':
    context=('cert/server.crt','cert/server.key')
    app.run(port=8080, debug=True, ssl_context=context)