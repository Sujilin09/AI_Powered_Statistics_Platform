from flask import session
from datetime import datetime
from your_project import get_db_connection  # import your DB connection function

@quiz_bp.route('/submit_quiz', methods=['POST'])
def submit_quiz():
    questions = session.get('quiz_questions', [])
    results = []
    score = 0

    for i, q in enumerate(questions):
        user_answer = request.form.get(f'q{i}')
        is_correct = user_answer == q['answer']
        if is_correct:
            score += 1
        results.append({
            'question': q['question'],
            'options': q['options'],
            'correct': q['answer'],
            'user_answer': user_answer
        })

    # 🔥 Save to DB
    if session.get('Email'):
        email = session['Email']
        topic = session.get('quiz_topic', 'Unknown')
        total = len(questions)
        dbconn = get_db_connection()
        cursor = dbconn.cursor()
        cursor.execute(
            "INSERT INTO quiz_scores (email, topic, score, total) VALUES (%s, %s, %s, %s)",
            (email, topic, score, total)
        )
        dbconn.commit()
        cursor.close()
        dbconn.close()

    return render_template('quiz_result.html', score=score, total=len(questions), results=results)
