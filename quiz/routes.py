from flask import Blueprint, render_template, request, session, flash
from .utils import generate_mcqs_from_textbook, generate_questions_from_prompt
from app import mysql  # Import the shared mysql instance from app.py

# This blueprint will contain all routes for your quiz module.
quiz_bp = Blueprint('quiz', __name__)

@quiz_bp.route('/', methods=['GET'])
def quiz_home():
    """Renders the main quiz home page."""
    return render_template('quiz_home.html')

@quiz_bp.route('/start', methods=['POST'])
def start_quiz():
    """Starts a quiz, generates questions, and stores them in the session."""
    quiz_type = request.form.get('quiz_type')
    questions = []
    topic = 'Unknown'

    if quiz_type == 'pdf':
        pdf = request.files.get('pdf')
        if pdf and pdf.filename:
            result = generate_mcqs_from_textbook(pdf)
            questions = result.get("questions", [])
            topic = f"Quiz from {pdf.filename}"

    elif quiz_type == 'prompt':
        prompt = request.form.get('prompt', '').strip()
        if prompt:
            result = generate_questions_from_prompt(prompt)
            questions = result.get("questions", [])
            topic = prompt
            if not questions:
                flash("The AI model could not generate questions for that topic. Please try another.", "warning")

    session['quiz'] = questions
    session['quiz_topic'] = topic
    return render_template('quiz_display.html', questions=questions)

@quiz_bp.route('/submit', methods=['POST'])
def submit_quiz():
    """
    Submits the quiz, calculates score, saves it to the database,
    and displays the results. This is the corrected version of your function.
    """
    questions = session.get('quiz', [])
    score = 0
    results = []

    for i, q in enumerate(questions):
        user_answer = request.form.get(f"q{i}")
        is_correct = user_answer == q.get('answer')
        if is_correct:
            score += 1
        
        results.append({
            "question": q.get('question'),
            "options": q.get('options', []),
            "correct": q.get('answer'),
            "user_answer": user_answer
        })

    # ✅ Save score to DB using the imported 'mysql' object
    if 'Email' in session:
        email = session['Email']
        topic = session.get('quiz_topic', 'Unknown')
        total_questions = len(questions)
        
        try:
            cursor = mysql.connection.cursor()
            cursor.execute(
                "INSERT INTO quiz_scores (email, topic, score, total) VALUES (%s, %s, %s, %s)",
                (email, topic, score, total_questions)
            )
            mysql.connection.commit()
            cursor.close()
        except Exception as e:
            print(f"Database Error: {e}")
            flash("Sorry, we couldn't save your score due to a database error.", "danger")

    # ✅ Clear session after submission
    session.pop('quiz', None)
    session.pop('quiz_topic', None)

    return render_template("quiz_result.html", score=score, total=len(questions), results=results)

