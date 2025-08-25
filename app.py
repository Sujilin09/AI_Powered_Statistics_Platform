from flask import Flask, render_template, request, redirect, session
from flask_mysqldb import MySQL
from werkzeug.security import generate_password_hash, check_password_hash
import os
import io
import base64
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# --- App Setup & Configuration ---
app = Flask(__name__)
app.secret_key = 'your_secret_key'

# --- Database Configuration ---
app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = '##Ss090503##'
app.config['MYSQL_DB'] = 'stat_analyser'
app.config['MYSQL_CURSORCLASS'] = 'DictCursor' 

# --- Database Initialization ---
# Initialize MySQL AFTER configuring the app
mysql = MySQL(app)

# CRITICAL: Make mysql accessible to blueprints by storing it as an app attribute
app.mysql = mysql

# --- Import all your blueprints AFTER mysql is configured ---
from quiz.quiz_app import quiz_bp
from calculator import calculator_bp
from analyzer.analyzer import analyzer_bp
from StatBot.bot_app import bot_bp

# --- Core User & Authentication Routes ---

@app.route('/index')
def index():
    if not session.get('loggedin'):
        return redirect('/')
        
    user_email = session.get('Email')
    user_name = session.get('user_name')
    plot_url = None

    try:
        cursor = mysql.connection.cursor()
        cursor.execute("SELECT score, total, taken_on FROM quiz_scores WHERE email = %s ORDER BY taken_on ASC LIMIT 10", (user_email,))
        data = cursor.fetchall()
        
        if data:
            # Generate the plot for quiz scores
            dates = [d['taken_on'].strftime("%d %b") for d in data]
            scores = [d['score'] for d in data]
            totals = [d['total'] for d in data]

            fig, ax = plt.subplots(figsize=(8, 4))
            fig.patch.set_facecolor('#f8f9fa')
            ax.set_facecolor('#ffffff')
            ax.plot(dates, scores, marker='o', linestyle='-', color="#00cc99", linewidth=2.5, label='Score')
            ax.plot(dates, totals, marker='o', linestyle='--', color="#999999", linewidth=2, label='Total')
            ax.set_xlabel('Date', fontsize=12)
            ax.set_ylabel('Score', fontsize=12)
            ax.set_ylim(0, max(totals) + 1 if totals else 10)
            ax.legend()
            ax.grid(True, linestyle='--', linewidth=0.5, alpha=0.6)
            plt.tight_layout()
            
            buf = io.BytesIO()
            plt.savefig(buf, format='png')
            buf.seek(0)
            plot_url = base64.b64encode(buf.getvalue()).decode()
            plt.close(fig)
    except Exception as e:
        print(f"Error generating plot: {e}")
    finally:
        if 'cursor' in locals() and cursor:
            cursor.close()

    return render_template("index.html", plot_url=plot_url, user_name=user_name)

@app.route("/", methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['Email']
        password = request.form['Password']
        cursor = mysql.connection.cursor()
        cursor.execute('SELECT * FROM usertable WHERE Email = %s', (email,))
        account = cursor.fetchone()
        cursor.close()
        
        if account and check_password_hash(account['Password'], password):
            session['loggedin'] = True
            session['user_id'] = account['id']
            session['Email'] = account['Email']
            session['user_name'] = account['user_name']
            return redirect('/index')
        else:
            return render_template('login.html', msg='Incorrect email/password!')
    return render_template('login.html')

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        user_name = request.form['user_name']
        email = request.form['email']
        password = request.form['password']
        
        cursor = mysql.connection.cursor()
        cursor.execute('SELECT * FROM usertable WHERE Email = %s', (email,))
        account = cursor.fetchone()
        
        if account:
            msg = 'Account already exists!'
        else:
            hashed_password = generate_password_hash(password)
            cursor.execute('INSERT INTO usertable (user_name, Email, Password) VALUES (%s, %s, %s)', (user_name, email, hashed_password))
            mysql.connection.commit()
            return redirect('/')
        cursor.close()
        return render_template('signup.html', msg=msg)
    return render_template('signup.html')

@app.route("/forget_password")
def forget_password():
    print("Forget password route hit")
    return render_template("forget_password.html")

@app.route("/reset_password", methods=['GET', 'POST'])
def reset_password():
    email = request.form.get("email")
    password = request.form.get("password")
    confirm_password = request.form.get("confirm_password")

    # Check if the email exists in the database
    cursor = mysql.connection.cursor()
    cursor.execute('SELECT * FROM usertable WHERE Email = %s', (email,))
    account = cursor.fetchone()

    if account:
        if password == confirm_password:
            # Hash the password for security
            hashed_password = generate_password_hash(password)
            cursor.execute("UPDATE usertable SET Password = %s WHERE Email = %s", (hashed_password, email))
            mysql.connection.commit()  # Commit the transaction
            cursor.close()
            msg = "Password reset successful!"
            return render_template('login.html', msg=msg)
        else:
            msg = "Re-entered password does not match the new password."
            return render_template("forget_password.html", msg=msg)
    else:
        msg = "Given email is not yet registered. Please sign up first."
        return render_template('signup.html', msg=msg)

# --- Register All Blueprints ---
app.register_blueprint(quiz_bp, url_prefix='/quiz')
app.register_blueprint(calculator_bp, url_prefix='/calculator')
app.register_blueprint(analyzer_bp, url_prefix='/analyzer')
app.register_blueprint(bot_bp, url_prefix='/bot') 

# --- Run Application ---
if __name__ == '__main__':
    print(f"[INFO] MySQL instance created: {mysql}")
    print(f"[INFO] MySQL accessible as app.mysql: {hasattr(app, 'mysql')}")
    app.run(debug=True)