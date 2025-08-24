from flask import *
import openai
import pandas as pd
from sentence_transformers import SentenceTransformer
import faiss
import numpy as np
import os
import mysql.connector 
from werkzeug.security import generate_password_hash, check_password_hash
from quiz.quiz_app import quiz_bp
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from MySQLdb import Error
from openai import OpenAI
import matplotlib
from analyzer.analyzer import analyzer_bp  #l
matplotlib.use('Agg')  # <-- Add this line first!

import matplotlib.pyplot as plt

import matplotlib.pyplot as plt
import io
import base64
from calculator import calculator_bp

app = Flask(__name__)
app.secret_key = 'your_secret_key'

app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = 'sandhika'
app.config['MYSQL_DB'] = 'project'

def get_db_connection():
    return mysql.connector.connect(
        host=app.config['MYSQL_HOST'],
        user=app.config['MYSQL_USER'],
        password=app.config['MYSQL_PASSWORD'],
        database=app.config['MYSQL_DB'],
        auth_plugin='mysql_native_password'
    )

@app.route('/index')
def index():
    session['loggedin'] = True if session.get('Email') else False
    user_email = session.get('Email')
    # ✅ 'id' comes from your usertable

    user_name = None  # <-- Add this
    plot_url = None

    if user_email:
        dbconn = get_db_connection()
        cursor = dbconn.cursor()
          # ✅ Fetch username
        cursor.execute("SELECT id,user_name FROM usertable WHERE Email = %s", (user_email,))
        user = cursor.fetchone()
        if user:
            session['user_id'] = user[0] 
            session['user_name'] = user[1]
            user_name = user[1]
            cursor.execute("""
            SELECT topic, score, total, taken_on 
            FROM quiz_scores 
            WHERE email = %s 
            ORDER BY taken_on ASC
            LIMIT 10
        """, (user_email,))
        data = cursor.fetchall()
        cursor.close()
        dbconn.close()

        if data:
            dates = [d[3].strftime("%d %b") for d in data]
            scores = [d[1] for d in data]
            totals = [d[2] for d in data]

            # Plot customization starts here
            fig, ax = plt.subplots(figsize=(8, 4))
            fig.patch.set_facecolor('#f8f9fa')  # Light theme background
            ax.set_facecolor('#ffffff')         # Plot background

            ax.plot(dates, scores, marker='o', linestyle='-', color="#00cc99", linewidth=2.5, label='Score')
            ax.plot(dates, totals, marker='o', linestyle='--', color="#999999", linewidth=2, label='Total')

            # ax.set_title('📈 Recent Quiz Scores', fontsize=14, color='#333333', weight='bold')
            ax.set_xlabel('Date', fontsize=12, color='#555555')
            ax.set_ylabel('Score', fontsize=12, color='#555555')
            ax.set_ylim(0, max(totals) + 1)

            ax.tick_params(axis='x', colors='#333333', labelrotation=45)
            ax.tick_params(axis='y', colors='#333333')

            ax.legend(facecolor='#f0f0f0', edgecolor='#dddddd')
            ax.grid(True, linestyle='--', linewidth=0.5, alpha=0.6)

            plt.tight_layout()
            buf = io.BytesIO()
            plt.savefig(buf, format='png', bbox_inches='tight')
            buf.seek(0)
            plot_url = base64.b64encode(buf.getvalue()).decode()
            plt.close(fig)

    return render_template("index.html", plot_url=plot_url,user_name=user_name)


@app.route("/logout")
def logout():
   session.pop("username", None)
   session.pop("password", None)
   session['loggedin'] = False
   return redirect("/")

@app.route("/", methods=['GET', 'POST'])
def login():
    if request.method == 'POST' and 'Email' in request.form and 'Password' in request.form:
        email = request.form['Email']
        password = request.form['Password']
        dbconn = get_db_connection()
        cursor = dbconn.cursor()
        cursor.execute('SELECT * FROM usertable WHERE Email = %s', (email,))
        account = cursor.fetchone()
        if account:
            if check_password_hash(account[3], password):
                session['loggedin'] = True
                session['Email'] = account[2]       # ✅ actual Email
                session['user_name'] = account[1]   # ✅ optional: store username
                return redirect('/index')
            else:
                msg = 'Incorrect email/password!'
                return render_template('login.html', msg=msg)
        else:
            msg = "Account not found. Signup first."
            return render_template('signup.html', msg=msg)
    return render_template('login.html')


@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        user_name = request.form.get('user_name')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        if password != confirm_password:
            msg = "Re-entered password does not match."
            return render_template('signup.html', msg=msg)
        hashed_password = generate_password_hash(password)
        dbconn = get_db_connection()
        cursor = dbconn.cursor()
        cursor.execute('SELECT * FROM usertable WHERE email = %s', (email,))
        account = cursor.fetchone()
        if account:
            msg = 'Account already exists!'
        else:
            cursor.execute('INSERT INTO usertable (user_name, email, password) VALUES (%s, %s, %s)', (user_name, email, hashed_password))
            dbconn.commit()
            msg = 'You have successfully registered!'
            return redirect('/index')
        return render_template('signup.html', msg=msg)
    return render_template('signup.html')

# Statbot

df = pd.read_csv("statbot_real_500_concepts.csv")
concepts = df["concept"].tolist()
descriptions = df["description"].tolist()

model = SentenceTransformer('all-MiniLM-L6-v2')
concept_embeddings = model.encode(concepts, convert_to_numpy=True)

embedding_dim = concept_embeddings.shape[1]
faiss_index = faiss.IndexFlatL2(embedding_dim)
faiss_index.add(concept_embeddings)

client = OpenAI(api_key="Open_AI_KEY")

chat_history = []

@app.route('/chat', methods=['POST'])
def chat():
    user_input = request.json.get("message")
    chat_history.append({"role": "user", "content": user_input})

    user_embedding = model.encode([user_input], convert_to_numpy=True)
    _, indices = faiss_index.search(user_embedding, k=3)
    context = "\n".join([f"{concepts[i]}: {descriptions[i]}" for i in indices[0]])

    messages = [
        {"role": "system", "content": (
            "You are StatBot, a friendly and helpful tutor in statistics. "
            "You should always answer questions clearly, explain concepts well, and add follow-up suggestions. "
            "Here are some useful context concepts:\n" + context
        )}
    ] + chat_history

    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=messages
        )
        bot_reply = response.choices[0].message.content
    except Exception as e:
        bot_reply = f"Error: {str(e)}"

    chat_history.append({"role": "assistant", "content": bot_reply})
    return jsonify({"reply": bot_reply})

@app.route('/bot')
def bot():
    return render_template('bot.html')

# Quiz Engine
app.register_blueprint(quiz_bp, url_prefix='/quiz')



###############33333
#Forget password
#######################3
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
    dbconn=get_db_connection()
    cursor=dbconn.cursor()
    cursor.execute('SELECT * FROM usertable WHERE Email = %s', (email,))
    account = cursor.fetchone()

    if account:
        if password == confirm_password:
            # Hash the password for security
            hashed_password = generate_password_hash(password)
            cursor.execute("UPDATE usertable SET Password = %s WHERE Email = %s", (hashed_password, email))
            dbconn.commit()  # Commit the transaction
            cursor.close()
            msg = "Password reset successful!"
            return render_template('login.html', msg=msg)
        else:
            msg = "Re-entered password does not match the new password."
            return render_template("forget_password.html", msg=msg)
    else:
        msg = "Given email is not yet registered. Please sign up first."
        return render_template('singup.html', msg=msg)
    



#calculator

app.register_blueprint(calculator_bp,url_prefix='/calculator')




# Register analyzer blueprint
app.register_blueprint(analyzer_bp, url_prefix='/analyzer')
if __name__ == '__main__':
    app.run(debug=True)

