# File: quiz/quiz_app.py
from flask import *
from  flask_mysqldb import MySQL
from quiz.utils import extract_text_from_pdf_advanced, generate_mcqs_from_textbook, generate_questions_from_prompt


quiz_bp = Blueprint('quiz', __name__)


app = Flask(__name__)
app.secret_key = 'your_secret_key'

app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = '##Ss090503##'
app.config['MYSQL_DB'] = 'stat_analyser'

mysql=MySQL(app)


@quiz_bp.route('/', methods=['GET'])
def quiz_home():
    return render_template('quiz_home.html')

@quiz_bp.route('/start', methods=['POST'])
def start_quiz():
    quiz_type = request.form['quiz_type']

    if quiz_type == 'pdf':
        pdf = request.files['pdf']
        if pdf:
            result = generate_mcqs_from_textbook(pdf)
            questions = result.get("questions", [])
        session['quiz_topic'] = 'PDF Quiz'


    elif quiz_type == 'prompt':
        prompt = request.form['prompt']
        questions = generate_questions_from_prompt(prompt)
        session['quiz_topic'] = prompt

    else:
        questions = []
        session['quiz_topic'] = 'Unknown'

    session['quiz'] = questions
    return render_template('quiz_display.html', questions=questions)

@quiz_bp.route('/submit', methods=['POST'])
def submit_quiz():
    questions = session.get('quiz', [])
    user_answers = [request.form.get(f"q{i}") for i in range(len(questions))]

    score = 0
    results = []

    for i, q in enumerate(questions):
        correct = q['answer']
        selected = user_answers[i]
        if selected == correct:
            score += 1
        results.append({
            "question": q['question'],
            "options": q['options'],
            "correct": correct,
            "user_answer": selected
        })

    # ✅ Save score to DB
    email = session.get('Email')
    topic = session.get('quiz_topic', 'Unknown')

    if email:  # Ensure user is logged in
        try:
            cursor = mysql.connection.cursor()
            cursor.execute(
                "INSERT INTO quiz_scores (email, topic, score, total) VALUES (%s, %s, %s, %s)",
                (email, topic, score, len(questions))
            )
            mysql.connection.commit()
            cursor.close()
        except Exception as e:
            print("DB Error:", e)

    # ✅ Clear session after submission
    session.pop('quiz', None)
    session.pop('quiz_topic', None)

    return render_template("quiz_result.html", score=score, total=len(questions), results=results)
